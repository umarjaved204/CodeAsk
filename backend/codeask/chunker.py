"""Split one file into chunks for embedding: by syntax (tree-sitter) where we have a grammar,
by token-packed line windows otherwise.

Why syntax: a function is the unit people ask about ("how is the key derived?"), so a chunk
that is exactly one function embeds one idea. And because embed_text holds no line numbers,
inserting a line above a function leaves its chunk (and cached embedding) unchanged. M0's fixed
windows cut functions in half and shifted every later chunk.

The algorithm is one idea applied at every level (module, class body, function body):
1. Units: each named child node is a unit. Own-line comments directly above a unit attach to
   it; units that share a line coalesce. Lines no node covers (clause lines such as `else:`,
   decorators, closing lines) become "glue" units, so coverage holds by construction.
2. A unit that fits under the cap is a leaf. A bigger one recurses into its body:
   class -> header (class line, docstring, attributes before the first member, plus a method
   outline in embed_text) + members; function / compound statement -> its statements, packed
   into parts that carry the enclosing header lines as context; anything else -> windows.
3. Siblings: only units below min_tokens merge, like with like (named with named, anonymous
   with anonymous), until the group reaches the target.

Invariants (tested, and swept over real repos):
- chunks are ascending and non-overlapping, and every non-blank line is in exactly one chunk
  (with window_overlap_lines = 0);
- lines are 1-based inclusive and content == file_lines[start-1:end];
- no embed_text exceeds max_tokens. A file with one line over the cap is skipped.

Token counts: each line is counted once and ranges are estimated by summing; only the final
embed_text is counted exactly (tokenizing joined text can differ slightly at the seams), and a
chunk over the cap is re-split exactly. Pure: the token counter is passed in.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Callable

import tree_sitter_python as tspy
from tree_sitter import Language, Parser

from codeask import config

CountTokens = Callable[[str], int]
# Bump when chunking output changes for the same input; recorded in repos.settings so M3
# results can be traced to the chunker that produced them.
CHUNKER_VERSION = "1"

LANG_BY_EXT = {".py": "python"}
_GRAMMARS = {"python": tspy.language}
_parsers: dict[str, Parser] = {}

PY_DEFINITIONS = {"function_definition": "function", "class_definition": "class"}
PY_COMPOUND = {"if_statement", "for_statement", "while_statement", "try_statement",
               "with_statement"}
# Tokens reserved in estimates for what the Scope line may add (merged names, "part i/n").
NAME_ALLOWANCE = 15


@dataclass(frozen=True)
class ChunkSettings:
    mode: str = config.CHUNKER
    target_min: int = config.TARGET_MIN_TOKENS
    target_max: int = config.TARGET_MAX_TOKENS
    max_tokens: int = config.MAX_TOKENS
    min_tokens: int = config.MIN_TOKENS
    window_overlap_lines: int = config.WINDOW_OVERLAP_LINES
    include_path: bool = config.EMBED_INCLUDE_PATH
    include_scope: bool = config.EMBED_INCLUDE_SCOPE
    max_context_headers: int = config.MAX_CONTEXT_HEADERS
    max_header_line_chars: int = config.MAX_HEADER_LINE_CHARS
    outline_max_tokens: int = config.OUTLINE_MAX_TOKENS
    max_names: int = config.MAX_NAMES_IN_SCOPE


@dataclass(frozen=True)
class Chunk:
    path: str
    start_line: int  # 1-based, inclusive
    end_line: int  # 1-based, inclusive
    kind: str  # function, class, class_header, merged, module, block, part, window
    name: str  # "" for anonymous chunks
    breadcrumb: str  # e.g. "Signer > derive_key", "<module>", "big (part 2/3)"
    content: str  # the raw file lines, what the UI shows
    embed_text: str  # what gets embedded (and hashed)
    token_count: int  # exact, of embed_text


@dataclass
class FileChunks:
    chunks: list[Chunk]
    method: str  # "ast", "windows", "fallback" (parse error), "empty" or "skipped"
    skip_reason: str | None = None


def chunk_file(path: str, text: str, count_tokens: CountTokens,
               settings: ChunkSettings = ChunkSettings()) -> FileChunks:
    """Chunk one file. `text` must already be normalized (filters.decode)."""
    return _FileChunker(path, text, count_tokens, settings).run()


class _LineTooLong(Exception):
    pass


@dataclass
class _Unit:
    start: int  # 0-based row, inclusive
    end: int
    node: object = None  # set only while the unit is exactly one node (so it can recurse)
    name: str | None = None
    kind: str = "anon"  # "function", "class" or "anon"
    sig_row: int | None = None  # row of the def/class line, for the class outline


@dataclass
class _Piece:
    start: int
    end: int
    kind: str
    scope: list[str]
    context: list[str]
    names: list[str] = field(default_factory=list)
    tokens: int = 0  # estimated code tokens
    named: bool = False
    final: bool = False  # produced by a split; never merged with siblings
    outline: str = ""
    part: tuple[int, int] | None = None


def _parser(lang: str) -> Parser:
    if lang not in _parsers:
        _parsers[lang] = Parser(Language(_GRAMMARS[lang]()))
    return _parsers[lang]


def _rows(node) -> tuple[int, int]:
    start, end = node.start_point[0], node.end_point[0]
    if node.end_point[1] == 0 and end > start:  # ends at column 0: really the previous line
        end -= 1
    return start, end


class _FileChunker:
    def __init__(self, path: str, text: str, count: CountTokens, settings: ChunkSettings):
        self.path, self.text, self.count, self.s = path, text, count, settings
        self.lines = text.split("\n")  # never splitlines(): see filters.decode
        if self.lines and self.lines[-1] == "":
            self.lines.pop()  # a final newline ends the last line; it isn't a line itself
        self.prefix = [0]
        for line in self.lines:
            self.prefix.append(self.prefix[-1] + count(line + "\n"))
        self._reserve_cache: dict = {}

    # ---------- entry ----------
    def run(self) -> FileChunks:
        if not any(line.strip() for line in self.lines):
            return FileChunks([], "empty")
        base = self._reserve([], [])
        if any(self._tokens(i, i) + base > self.s.max_tokens for i in range(len(self.lines))):
            return FileChunks([], "skipped", "line exceeds token cap")

        method, pieces = "windows", None
        lang = LANG_BY_EXT.get(PurePosixPath(self.path).suffix.lower())
        if lang and self.s.mode == "ast":
            root = _parser(lang).parse(self.text.encode("utf-8")).root_node
            if root.has_error:
                method = "fallback"  # tree-sitter repairs broken code silently; don't trust it
            else:
                method = "ast"
                units = self._with_glue(0, len(self.lines) - 1, self._units(root.named_children))
                pieces = self._level(units, [], [], pack=False)
        if pieces is None:
            pieces = [_Piece(s, e, "window", [], [], tokens=self._tokens(s, e), final=True)
                      for s, e in self._window_ranges(0, len(self.lines) - 1, base)]
        try:
            chunks = [chunk for piece in pieces for chunk in self._emit(piece)]
        except _LineTooLong:
            return FileChunks([], "skipped", "line exceeds token cap")
        return FileChunks(chunks, method)

    # ---------- token estimates ----------
    def _tokens(self, start: int, end: int) -> int:
        return self.prefix[end + 1] - self.prefix[start]

    def _head(self, breadcrumb: str) -> str:
        parts = []
        if self.s.include_path:
            parts.append(f"File: {self.path}")
        if self.s.include_scope:
            parts.append(f"Scope: {breadcrumb}")
        return "\n".join(parts) + "\n\n" if parts else ""

    def _reserve(self, scope: list[str], context: list[str]) -> int:
        """Tokens the File/Scope prefix and context lines will add to a chunk's code."""
        key = (tuple(scope), tuple(context))
        if key not in self._reserve_cache:
            ctx = "\n".join(context) + "\n...\n" if context else ""
            allowance = NAME_ALLOWANCE if self.s.include_scope else 0
            self._reserve_cache[key] = (
                self.count(self._head(" > ".join(scope) or "<module>") + ctx) + allowance)
        return self._reserve_cache[key]

    # ---------- units ----------
    def _describe(self, node):
        """(kind, name, inner node) for a top-level or body node."""
        inner = node.child_by_field_name("definition") if node.type == "decorated_definition" \
            else node
        if inner is not None and inner.type in PY_DEFINITIONS:
            name = inner.child_by_field_name("name")
            return PY_DEFINITIONS[inner.type], name.text.decode("utf-8", "replace") if name \
                else "?", inner
        return "anon", None, inner if inner is not None else node

    def _own_line(self, node) -> bool:
        row, col = node.start_point[0], node.start_point[1]
        return not self.lines[row][:col].strip()

    def _units(self, nodes) -> list[_Unit]:
        units, comments = [], []
        for node in nodes:
            start, end = _rows(node)
            if node.type == "comment":
                comments.append((start, end, node))
                continue
            kind, name, inner = self._describe(node)
            unit = _Unit(start, end, node, name, kind,
                         _rows(inner)[0] if kind != "anon" else None)
            # Contiguous own-line comments directly above (no blank line) attach to the unit.
            k, top = len(comments), start
            while k and comments[k - 1][1] == top - 1 and self._own_line(comments[k - 1][2]):
                k -= 1
                top = comments[k][0]
            units.extend(_Unit(cs, ce) for cs, ce, _ in comments[:k])
            comments = []
            unit.start = top
            units.append(unit)
        units.extend(_Unit(cs, ce) for cs, ce, _ in comments)
        return self._coalesce(units)

    def _coalesce(self, units: list[_Unit]) -> list[_Unit]:
        """Units that share a line become one unit (e.g. `MAX = 10  # constant`)."""
        out: list[_Unit] = []
        for unit in sorted(units, key=lambda u: (u.start, u.end)):
            if out and unit.start <= out[-1].end:
                prev = out[-1]
                if unit.end <= prev.end and unit.kind == "anon":
                    continue  # e.g. a trailing comment: absorbed, prev can still recurse
                named = prev if prev.kind != "anon" else unit if unit.kind != "anon" else None
                out[-1] = _Unit(prev.start, max(prev.end, unit.end), None,
                                named.name if named else None,
                                named.kind if named else "anon",
                                named.sig_row if named else None)
            else:
                out.append(unit)
        return out

    def _with_glue(self, start: int, end: int, children: list[_Unit]) -> list[_Unit]:
        """Children plus a unit for every run of non-blank lines that no child covers."""
        out, row = [], start
        for child in children:
            if child.start > row:
                self._add_gap(out, row, child.start - 1)
            out.append(child)
            row = max(row, child.end + 1)
        if row <= end:
            self._add_gap(out, row, end)
        return out

    def _add_gap(self, out: list[_Unit], start: int, end: int) -> None:
        while start <= end and not self.lines[start].strip():
            start += 1
        while end >= start and not self.lines[end].strip():
            end -= 1
        if start <= end:
            out.append(_Unit(start, end))

    def _expand(self, unit: _Unit):
        """(kind, header row, child units) for a unit too big to keep whole, or None."""
        if unit.node is None:
            return None
        kind, _, inner = self._describe(unit.node)
        if kind in ("class", "function"):
            body = inner.child_by_field_name("body")
            if body is None or not body.named_children:
                return None
            return kind, _rows(inner)[0], self._units(body.named_children)
        if inner.type in PY_COMPOUND:
            # Statements of every block, including clause blocks (elif/else/except/finally).
            # The clause lines themselves are covered by glue.
            stmts = []
            for child in inner.named_children:
                if child.type == "block":
                    stmts.extend(child.named_children)
                elif child.type.endswith("_clause"):
                    for grandchild in child.named_children:
                        if grandchild.type == "block":
                            stmts.extend(grandchild.named_children)
            if not stmts:
                return None
            return "compound", _rows(inner)[0], self._units(stmts)
        return None

    # ---------- levels ----------
    def _level(self, units: list[_Unit], scope: list[str], context: list[str],
               pack: bool) -> list[_Piece]:
        pieces = []
        for unit in units:
            tokens = self._tokens(unit.start, unit.end)
            if tokens + self._reserve(scope, context) <= self.s.max_tokens:
                named = unit.kind != "anon"
                kind = unit.kind if named else ("module" if not scope else "block")
                pieces.append(_Piece(unit.start, unit.end, kind, scope, context,
                                     [unit.name] if named else [], tokens, named))
            else:
                pieces.extend(self._split(unit, scope, context))
        return self._pack(pieces) if pack else self._merge(pieces)

    def _split(self, unit: _Unit, scope: list[str], context: list[str]) -> list[_Piece]:
        own_scope = scope + [unit.name] if unit.name else scope
        expanded = self._expand(unit)
        if expanded is None:
            reserve = self._reserve(own_scope, context)
            pieces = [_Piece(s, e, "window", own_scope, context, tokens=self._tokens(s, e),
                             final=True)
                      for s, e in self._window_ranges(unit.start, unit.end, reserve)]
            return self._label_parts(pieces) if unit.name else pieces

        kind, header_row, children = expanded
        inner_context = (context + [self._header_line(header_row)])[-self.s.max_context_headers:]
        units = self._with_glue(unit.start, unit.end, children)

        if kind == "class":
            i = 0
            while i < len(units) and units[i].kind == "anon":
                i += 1
            members, out = units[i:], []
            if i:
                start, end = units[0].start, units[i - 1].end
                outline = self._outline(members)
                tokens = self._tokens(start, end)
                fits = (tokens + self._reserve(own_scope, context) + self.count(outline)
                        <= self.s.max_tokens)
                if fits:
                    out.append(_Piece(start, end, "class_header", scope, context, [unit.name],
                                      tokens, True, final=True, outline=outline))
                else:
                    # A long docstring: window the header, but keep the outline on part 1
                    # (every window reserves room for it, so the cap can't push it out).
                    reserve = self._reserve(own_scope, context) + self.count(outline)
                    parts = self._label_parts([
                        _Piece(s, e, "part", own_scope, context, tokens=self._tokens(s, e),
                               final=True)
                        for s, e in self._window_ranges(start, end, reserve)])
                    parts[0].kind, parts[0].outline = "class_header", outline
                    out.extend(parts)
            for piece in self._level(members, own_scope, inner_context, pack=False):
                piece.final = True
                out.append(piece)
            return out

        pieces = self._level(units, own_scope, inner_context, pack=True)
        for piece in pieces:
            piece.final = True
        return self._label_parts(pieces) if unit.name else pieces

    def _label_parts(self, pieces: list[_Piece]) -> list[_Piece]:
        unlabeled = [p for p in pieces if p.part is None]
        if len(unlabeled) > 1:
            for i, piece in enumerate(unlabeled, 1):
                piece.part, piece.kind, piece.names = (i, len(unlabeled)), "part", []
        return pieces

    def _merge(self, pieces: list[_Piece]) -> list[_Piece]:
        """Siblings: only units below min_tokens merge, like with like, up to the target."""
        out, group = [], []
        for piece in pieces:
            if piece.final or piece.tokens >= self.s.min_tokens:
                out.extend(self._flush(group))
                out.append(piece)
                continue
            if group and (group[0].named != piece.named
                          or sum(p.tokens for p in group) + piece.tokens > self.s.target_max):
                out.extend(self._flush(group))
            group.append(piece)
            if sum(p.tokens for p in group) >= self.s.target_min:
                out.extend(self._flush(group))
        out.extend(self._flush(group))
        return out

    def _pack(self, pieces: list[_Piece]) -> list[_Piece]:
        """Parts of one split unit: pack consecutive pieces greedily up to the target."""
        out, group = [], []
        for piece in pieces:
            if piece.final:
                out.extend(self._flush(group))
                out.append(piece)
                continue
            if group and sum(p.tokens for p in group) + piece.tokens > self.s.target_max:
                out.extend(self._flush(group))
            group.append(piece)
        out.extend(self._flush(group))
        return out

    def _flush(self, group: list[_Piece]) -> list[_Piece]:
        if not group:
            return []
        first = group[0]
        if len(group) == 1:
            combined = first
        else:
            named = all(p.named for p in group)
            kind = "merged" if named else ("module" if not first.scope else "block")
            combined = _Piece(first.start, group[-1].end, kind, first.scope, first.context,
                              [n for p in group for n in p.names],
                              sum(p.tokens for p in group), named)
        group.clear()
        return [combined]

    # ---------- windows ----------
    def _window_ranges(self, start: int, end: int, reserve: int) -> list[tuple[int, int]]:
        """Token-packed line windows over [start, end], never past the cap, no overlap
        unless window_overlap_lines > 0."""
        budget = min(self.s.target_max, self.s.max_tokens - reserve)
        out, i = [], start
        while i <= end:
            while i <= end and not self.lines[i].strip():
                i += 1
            if i > end:
                break
            j, tokens = i, self._tokens(i, i)
            while j + 1 <= end and tokens + self._tokens(j + 1, j + 1) <= budget:
                j += 1
                tokens += self._tokens(j, j)
            while not self.lines[j].strip():
                j -= 1
            out.append((i, j))
            nxt = j + 1
            if self.s.window_overlap_lines and nxt <= end:
                nxt = max(i + 1, nxt - self.s.window_overlap_lines)
            i = nxt
        return out

    # ---------- output ----------
    def _header_line(self, row: int) -> str:
        return self.lines[row][:self.s.max_header_line_chars].rstrip()

    def _outline(self, members: list[_Unit]) -> str:
        sigs = [self.lines[m.sig_row].strip()[:self.s.max_header_line_chars]
                for m in members if m.kind != "anon" and m.sig_row is not None]
        for keep in range(len(sigs), 0, -1):
            rest = len(sigs) - keep
            text = "Members:\n" + "\n".join(f"  {s}" for s in sigs[:keep]) + (
                f"\n  ... +{rest} more" if rest else "")
            if self.count(text) <= self.s.outline_max_tokens:
                return text
        return f"Members: {len(sigs)}" if sigs else ""

    def _names_label(self, names: list[str]) -> str:
        if len(names) > self.s.max_names:
            return ", ".join(names[:self.s.max_names]) + f" +{len(names) - self.s.max_names} more"
        return ", ".join(names)

    def _breadcrumb(self, piece: _Piece) -> str:
        base = " > ".join(piece.scope)
        if piece.part:
            return f"{base or '<module>'} (part {piece.part[0]}/{piece.part[1]})"
        if piece.names:
            return " > ".join(piece.scope + [self._names_label(piece.names)])
        return base or "<module>"

    def _build(self, piece: _Piece, start: int, end: int) -> Chunk:
        code = "\n".join(self.lines[start:end + 1])
        breadcrumb = self._breadcrumb(piece)
        body = "\n".join(piece.context) + "\n...\n" + code if piece.context else code
        if piece.outline:
            body += "\n\n" + piece.outline
        embed_text = self._head(breadcrumb) + body
        return Chunk(self.path, start + 1, end + 1, piece.kind, self._names_label(piece.names),
                     breadcrumb, code, embed_text, self.count(embed_text))

    def _emit(self, piece: _Piece) -> list[Chunk]:
        chunk = self._build(piece, piece.start, piece.end)
        if chunk.token_count <= self.s.max_tokens:
            return [chunk]
        # The estimate drifted at the seams: re-split this range with exact counts.
        base, out, i = replace(piece, outline=""), [], piece.start
        while i <= piece.end:
            while i <= piece.end and not self.lines[i].strip():
                i += 1
            if i > piece.end:
                break
            # The outline (class headers) stays on the first sub-window if it fits at all.
            for current in ([piece] if not out else []) + [base, replace(base, context=[])]:
                if self._build(current, i, i).token_count <= self.s.max_tokens:
                    break
            else:
                raise _LineTooLong
            j = i
            while j + 1 <= piece.end and \
                    self._build(current, i, j + 1).token_count <= self.s.max_tokens:
                j += 1
            while not self.lines[j].strip():
                j -= 1
            out.append(self._build(current, i, j))
            i = j + 1
        return out
