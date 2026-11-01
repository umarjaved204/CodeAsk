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

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Callable

import tree_sitter_javascript as tsjs
import tree_sitter_python as tspy
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser

from codeask import config, markdown

CountTokens = Callable[[str], int]
# Bump when chunking output changes for the same input; recorded in repos.settings so M3
# results can be traced to the chunker that produced them.
# 2: JS/TS, closing-bracket glue, sibling decorators attach.
# 3: Markdown/reST sections, embed-only noise stripping, window polish + "(part i)" labels.
# 4: /** */ doc comments attach across one blank line; file-level JSDoc tags stay standalone.
CHUNKER_VERSION = "4"
# JSDoc blocks that describe a file or a type, not the code below them: never attached.
JSDOC_STANDALONE_TAGS = ("@file", "@fileoverview", "@module", "@license", "@copyright",
                         "@typedef", "@callback", "@namespace")

# Tokens reserved in estimates for what the Scope line may add (merged names, "part i/n").
NAME_ALLOWANCE = 15
MAX_CALL_NAME_CHARS = 60
# Glue made only of closing brackets (`}`, `});`, `]`) attaches to the unit before it, so a
# class's last `}` isn't a stranded one-line chunk. Python never produces such glue.
CLOSING_ONLY = re.compile(r"^[\]\)\};,]+$")

_parsers: dict[str, Parser] = {}


def _text(node) -> str:
    return node.text.decode("utf-8", "replace")


def _short(node) -> str:
    text = " ".join(_text(node).split())
    return text if len(text) <= MAX_CALL_NAME_CHARS else text[:MAX_CALL_NAME_CHARS - 3] + "..."


# ---------- languages ----------
# describe(node) -> (kind, name, inner, header_row): kind is "function", "class", "type" or
# "anon"; inner is the node whose "body" field holds the children to recurse into; header_row
# is the line carried as context by split pieces (and listed in a class outline).

PY_DEFINITIONS = {"function_definition": "function", "class_definition": "class"}


def _py_describe(node):
    inner = node.child_by_field_name("definition") if node.type == "decorated_definition" \
        else node
    if inner is not None and inner.type in PY_DEFINITIONS:
        name = inner.child_by_field_name("name")
        return PY_DEFINITIONS[inner.type], _text(name) if name else "?", inner, _rows(inner)[0]
    inner = inner if inner is not None else node
    return "anon", None, inner, _rows(inner)[0]


def _py_window_reason(node, kind):
    return "named without block body" if kind != "anon" else "oversized anonymous unit"


JS_FN = {"arrow_function", "function_expression", "function", "generator_function"}
JS_FUNC_DECL = {"function_declaration", "generator_function_declaration", "function_signature"}
JS_CLASS_DECL = {"class_declaration", "abstract_class_declaration"}
JS_TYPE_DECL = {"interface_declaration", "type_alias_declaration", "enum_declaration"}
JS_MEMBER_FN = {"method_definition", "method_signature", "abstract_method_signature"}


def _js_callback(call):
    """The last function argument with a block body, e.g. the handler in app.get(...)."""
    args = call.child_by_field_name("arguments")
    fns = [a for a in (args.named_children if args else []) if a.type in JS_FN]
    if fns:
        body = fns[-1].child_by_field_name("body")
        if body is not None and body.type == "statement_block":
            return fns[-1]
    return None


def _js_statement_call(node):
    if node.type == "expression_statement" and node.named_children \
            and node.named_children[0].type == "call_expression":
        return node.named_children[0]
    return None


def _js_describe(node):
    row = _rows(node)[0]
    inner = node
    if node.type == "export_statement":
        decl = node.child_by_field_name("declaration")
        if decl is None:  # export default <expression>
            value = node.child_by_field_name("value")
            if value is not None and value.type in JS_FN:
                return "function", "default", value, row
            if value is not None and value.type == "class":
                return "class", "default", value, row
            return "anon", None, node, row
        inner = decl
    t = inner.type
    if t in JS_CLASS_DECL or t in JS_FUNC_DECL or t in JS_TYPE_DECL or t in JS_MEMBER_FN:
        kind = "class" if t in JS_CLASS_DECL else "type" if t in JS_TYPE_DECL else "function"
        name = inner.child_by_field_name("name")
        return kind, _text(name) if name else "default", inner, _rows(inner)[0]
    if t in ("lexical_declaration", "variable_declaration"):
        decl = next((c for c in inner.named_children if c.type == "variable_declarator"), None)
        value = decl.child_by_field_name("value") if decl is not None else None
        if value is not None and (value.type in JS_FN or value.type == "class"):
            kind = "class" if value.type == "class" else "function"
            return kind, _text(decl.child_by_field_name("name")), value, row
        return "anon", None, node, row
    if t == "expression_statement" and inner.named_children:
        expr = inner.named_children[0]
        if expr.type == "internal_module":  # TS namespace: a container, like a class
            name = expr.child_by_field_name("name")
            return "class", _text(name) if name else "namespace", expr, row
        if expr.type == "assignment_expression":  # app.handle = function handle(...) {...}
            right = expr.child_by_field_name("right")
            if right is not None and right.type in JS_FN:
                return "function", _short(expr.child_by_field_name("left")), right, row
        if expr.type == "call_expression":
            # Named only for callback calls whose first argument is a string/template literal:
            # app.get("/users/:id", ...), describe("Router", ...), it("works", ...).
            args = expr.child_by_field_name("arguments")
            first = args.named_children[0] if args and args.named_children else None
            callback = _js_callback(expr)
            if callback is not None and first is not None \
                    and first.type in ("string", "template_string"):
                callee = expr.child_by_field_name("function")
                return "function", _short(callee) + "(" + _short(first) + ")", callback, row
    return "anon", None, node, row


def _has_object(node, depth):
    return node.type == "object" or (
        depth > 0 and any(_has_object(c, depth - 1) for c in node.named_children))


def _js_window_reason(node, kind):
    expr = node.named_children[0] if node.type == "expression_statement" \
        and node.named_children else None
    if expr is not None:
        call = expr
        if call.type in ("parenthesized_expression", "unary_expression") and call.named_children:
            call = call.named_children[0]
        if call.type == "call_expression":
            fn = call.child_by_field_name("function")
            if fn is not None and fn.type == "parenthesized_expression" and fn.named_children:
                fn = fn.named_children[0]
            if fn is not None and fn.type in JS_FN:
                return "IIFE"
        if expr.type == "assignment_expression" and \
                getattr(expr.child_by_field_name("right"), "type", None) == "object":
            return "object literal"
    if node.type in ("export_statement", "lexical_declaration", "variable_declaration") and \
            _has_object(node, 3):  # export default {...} / const routes = {...}
        return "object literal"
    return "named without block body" if kind != "anon" else "oversized anonymous unit"


@dataclass(frozen=True)
class _Lang:
    grammar: Callable
    describe: Callable
    window_reason: Callable
    body_types: frozenset  # node types a definition's "body" must have to be recursed into
    blocks: frozenset  # statement containers inside compound statements
    clauses: Callable  # node type -> is it a clause (elif/else/except/catch/finally)?
    compound: frozenset
    attachable: frozenset  # sibling nodes that attach to the unit below (comments, decorators)
    callback: Callable  # anonymous statement -> callback function to recurse into, or None
    jsdoc: bool = False  # /** */ doc comments (attach across a blank line; standalone tags)


_PY = _Lang(
    grammar=tspy.language, describe=_py_describe, window_reason=_py_window_reason,
    body_types=frozenset({"block"}), blocks=frozenset({"block"}),
    clauses=lambda t: t.endswith("_clause"),
    compound=frozenset({"if_statement", "for_statement", "while_statement", "try_statement",
                        "with_statement"}),
    attachable=frozenset({"comment"}), callback=lambda node: None)


def _js_lang(grammar):
    return _Lang(
        grammar=grammar, describe=_js_describe, window_reason=_js_window_reason,
        body_types=frozenset({"statement_block", "class_body"}),
        blocks=frozenset({"statement_block", "switch_body"}),
        clauses=lambda t: t in ("else_clause", "catch_clause", "finally_clause"),
        compound=frozenset({"if_statement", "for_statement", "for_in_statement",
                            "while_statement", "do_statement", "try_statement",
                            "switch_statement", "with_statement"}),
        attachable=frozenset({"comment", "decorator"}),
        callback=lambda node: _js_callback(c) if (c := _js_statement_call(node)) else None,
        jsdoc=True)


LANGS = {
    "python": _PY,
    "javascript": _js_lang(tsjs.language),
    "typescript": _js_lang(tsts.language_typescript),
    "tsx": _js_lang(tsts.language_tsx),
}
LANG_BY_EXT = {".py": "python",
               ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
               ".cjs": "javascript",
               ".ts": "typescript", ".mts": "typescript", ".cts": "typescript",
               ".tsx": "tsx"}


def language_for(path: str) -> str | None:
    """Grammar name for a path. Declaration files (.d.ts) take precedence over .ts: they are
    skipped by the filters, and never parsed here."""
    name = PurePosixPath(path).name.lower()
    if name.endswith((".d.ts", ".d.mts", ".d.cts")):
        return None
    return LANG_BY_EXT.get(PurePosixPath(path).suffix.lower())


@dataclass(frozen=True)
class ChunkSettings:
    mode: str = config.CHUNKER
    target_min: int = config.TARGET_MIN_TOKENS
    target_max: int = config.TARGET_MAX_TOKENS
    max_tokens: int = config.MAX_TOKENS
    min_tokens: int = config.MIN_TOKENS
    window_overlap_lines: int = config.WINDOW_OVERLAP_LINES
    window_prefer_blank_lines: bool = config.WINDOW_PREFER_BLANK_LINES
    jsdoc_attach_across_blank: bool = config.JSDOC_ATTACH_ACROSS_BLANK
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
    # Why units inside an AST-chunked file fell back to windows, e.g. {"IIFE": 1}.
    window_reasons: Counter = field(default_factory=Counter)
    # Docs: lines over the token cap, truncated in embed_text only (content stays intact).
    truncated_lines: int = 0


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
    kind: str = "anon"  # "function", "class", "type" or "anon"
    sig_row: int | None = None  # row of the def/class line, for the class outline
    origin: str = "node"  # "node", "glue" (lines no node covers) or "composite" (coalesced)


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
    part: tuple[int, int | None] | None = None  # (i, n); n is None for whole-file windows


def _parser(lang: str) -> Parser:
    if lang not in _parsers:
        _parsers[lang] = Parser(Language(LANGS[lang].grammar()))
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
        self._reserve_cache: dict = {}
        self.lang: _Lang | None = None
        self.window_reasons: Counter = Counter()
        self.truncated_lines = 0
        self.is_doc = PurePosixPath(path).suffix.lower() in markdown.DOC_EXT
        self.root = "<document>" if self.is_doc else "<module>"
        self.fences: list[tuple[int, int]] = []
        # What gets embedded per line. Code: the line itself. Docs: None for noise (badges,
        # link definitions, front matter) and over-cap lines truncated; `self.lines` (what the
        # UI shows and citations point at) is never changed.
        self.embed_lines: list[str | None] = self._doc_embed_lines() if self.is_doc \
            else self.lines
        self.prefix = [0]
        for line in self.embed_lines:
            self.prefix.append(self.prefix[-1] + (count(line + "\n") if line is not None else 0))

    # ---------- entry ----------
    def run(self) -> FileChunks:
        if not any(line.strip() for line in self.lines):
            return FileChunks([], "empty")
        base = self._reserve([], [])
        if not self.is_doc and any(self._tokens(i, i) + base > self.s.max_tokens
                                   for i in range(len(self.lines))):
            return FileChunks([], "skipped", "line exceeds token cap")

        method, pieces = "windows", None
        lang = language_for(self.path)
        if self.is_doc and self.s.mode == "ast":
            method, pieces = "ast", self._doc_pieces()
        elif lang and self.s.mode == "ast":
            self.lang = LANGS[lang]
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
            if len(pieces) > 1:
                # "(part 2)" without a total: appending to a file must not relabel (and so
                # re-embed) every earlier window.
                for i, piece in enumerate(pieces, 1):
                    piece.part = (i, None)
        try:
            chunks = [chunk for piece in pieces for chunk in self._emit(piece)]
        except _LineTooLong:
            return FileChunks([], "skipped", "line exceeds token cap")
        return FileChunks(chunks, method, window_reasons=self.window_reasons,
                          truncated_lines=self.truncated_lines)

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
                self.count(self._head(" > ".join(scope) or self.root) + ctx) + allowance)
        return self._reserve_cache[key]

    # ---------- units ----------
    def _own_line(self, node) -> bool:
        row, col = node.start_point[0], node.start_point[1]
        return not self.lines[row][:col].strip()

    def _attaches(self, comment, top: int, allow_blank_hop: bool) -> bool:
        start, end, node = comment
        if not self._own_line(node):
            return False
        text = _text(node) if self.lang.jsdoc and node.type == "comment" else ""
        if text.startswith("/*") and any(tag in text for tag in JSDOC_STANDALONE_TAGS):
            return False  # describes the file or a type, not the code below
        if end == top - 1:
            return True
        return (allow_blank_hop and end == top - 2 and not self.lines[top - 1].strip()
                and text.startswith("/**"))

    def _units(self, nodes) -> list[_Unit]:
        units, comments = [], []
        for node in nodes:
            start, end = _rows(node)
            if node.type in self.lang.attachable:  # comments; sibling decorators in TS
                comments.append((start, end, node))
                continue
            kind, name, _, header_row = self.lang.describe(node)
            unit = _Unit(start, end, node, name, kind, header_row if kind != "anon" else None)
            # Contiguous own-line comments directly above (no blank line) attach to the unit.
            # The nearest one may instead be a /** */ doc comment one blank line above a
            # named unit (JSDoc style); everything above it must still be contiguous.
            k, top = len(comments), start
            hop = (self.lang.jsdoc and self.s.jsdoc_attach_across_blank and kind != "anon")
            while k and self._attaches(comments[k - 1], top, hop):
                k -= 1
                top = comments[k][0]
                hop = False
            units.extend(_Unit(cs, ce, origin="comment") for cs, ce, _ in comments[:k])
            comments = []
            unit.start = top
            units.append(unit)
        units.extend(_Unit(cs, ce, origin="comment") for cs, ce, _ in comments)
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
                                named.sig_row if named else None, origin="composite")
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
        if start > end:
            return
        closing_only = all(CLOSING_ONLY.match(self.lines[i].strip()) or not self.lines[i].strip()
                           for i in range(start, end + 1))
        if out and closing_only:
            out[-1].end = end  # `}` / `});` belongs with the unit it closes
        else:
            out.append(_Unit(start, end, origin="glue"))

    def _expand(self, unit: _Unit):
        """(kind, header row, child units) for a unit too big to keep whole, or None."""
        if unit.node is None:
            return None
        lang = self.lang
        kind, _, inner, header_row = lang.describe(unit.node)
        if kind == "anon" and (callback := lang.callback(unit.node)) is not None:
            kind, inner = "function", callback  # e.g. app.use(function (req, res) {...})
        if kind in ("class", "function"):
            body = inner.child_by_field_name("body")
            if body is None or body.type not in lang.body_types or not body.named_children:
                return None
            return kind, header_row, self._units(body.named_children)
        if inner.type in lang.compound:
            # Statements of every block, including clause blocks (elif/else/except/catch/
            # finally); `else if` chains recurse as nested statements. Clause lines themselves
            # (`else:`, `} else {`) are covered by glue.
            stmts = []
            for child in inner.named_children:
                if child.type in lang.blocks:
                    stmts.extend(child.named_children)
                elif lang.clauses(child.type):
                    for grandchild in child.named_children:
                        if grandchild.type in lang.blocks:
                            stmts.extend(grandchild.named_children)
                        elif grandchild.type in lang.compound:
                            stmts.append(grandchild)
            if not stmts:
                return None
            return "compound", header_row, self._units(stmts)
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
            self.window_reasons[self._window_reason(unit)] += 1
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
                    self.window_reasons["class header over cap"] += 1
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

    def _window_reason(self, unit: _Unit) -> str:
        """Why an over-cap unit couldn't recurse and fell back to windows (sweep report)."""
        if unit.origin == "composite":
            return "shared-line composite"  # e.g. `a(); b();` or K&R-style shared lines
        if unit.origin in ("glue", "comment"):
            return f"oversized {unit.origin}"
        if unit.node is None:
            return "other"
        return self.lang.window_reason(unit.node, unit.kind)

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

    # ---------- docs (Markdown / reST) ----------
    def _doc_embed_lines(self) -> list[str | None]:
        rst = self.path.lower().endswith(".rst")
        front_end = -1 if rst else markdown.front_matter_end(self.lines)
        # Fences are Markdown only: in reST `~~~~` is an underline, and code blocks are
        # indented after `::` (already excluded, since titles can't be indented).
        self.fences = [] if rst else markdown.fence_ranges(self.lines, front_end + 1)
        fenced = {r for first, last in self.fences for r in range(first, last + 1)}
        self._doc_skip = fenced | set(range(front_end + 1))
        # Room left for one line once the File/Scope prefix (with a long breadcrumb) is added.
        budget = self.s.max_tokens - self._reserve([], []) - 20
        out: list[str | None] = []
        for i, line in enumerate(self.lines):
            if i <= front_end or (i not in fenced and markdown.is_noise(line)):
                out.append(None)  # front matter, badges, link definitions: not embedded
                continue
            if self.count(line + "\n") > budget:
                line = self._truncate(line, budget)
                self.truncated_lines += 1
            out.append(line)
        return out

    def _truncate(self, line: str, budget: int) -> str:
        """Longest prefix of `line` that fits the budget (binary search on characters)."""
        lo, hi = 0, len(line)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.count(line[:mid] + " ...\n") <= budget:
                lo = mid
            else:
                hi = mid - 1
        return line[:lo] + " ..."

    def _trim(self, start: int, end: int) -> int:
        while end > start and not self.lines[end].strip():
            end -= 1
        return end

    def _doc_pieces(self) -> list[_Piece]:
        """Sections at H1/H2 (breadcrumb H1 > H2); an over-cap section splits at its next
        heading level, then by paragraph, then windows. Small sections merge like code."""
        rst = self.path.lower().endswith(".rst")
        self._headings = markdown.headings(self.lines, rst, self._doc_skip)
        last = len(self.lines) - 1
        tops = [h for h in self._headings if h.level <= 2]
        pieces = []
        first_row = tops[0].row if tops else last + 1
        if any(line.strip() for line in self.lines[:first_row]):
            pieces.extend(self._doc_unit(0, self._trim(0, first_row - 1), None, 0, []))
        h1 = None
        for k, h in enumerate(tops):
            end = self._trim(h.row, tops[k + 1].row - 1 if k + 1 < len(tops) else last)
            if h.level == 1:
                h1, scope = h.name, []
            else:
                scope = [h1] if h1 else []
            pieces.extend(self._doc_unit(h.row, end, h.name or "(untitled)", h.level, scope))
        return self._attach_empty(self._merge(pieces))

    def _doc_unit(self, start: int, end: int, name: str | None, level: int,
                  scope: list[str]) -> list[_Piece]:
        tokens = self._tokens(start, end)
        if tokens + self._reserve(scope, []) <= self.s.max_tokens:
            return [_Piece(start, end, "section" if name else "intro", scope, [],
                           [name] if name else [], tokens, bool(name))]
        own_scope = scope + [name] if name else scope
        inner = [h for h in self._headings if start < h.row <= end and h.level > level]
        if not inner:
            return self._doc_paragraphs(start, end, own_scope, named=bool(name))
        sub_level = min(h.level for h in inner)
        subs = [h for h in inner if h.level == sub_level]
        out = []
        # The section's head (its heading + intro text) keeps the section's own name.
        head_end = self._trim(start, subs[0].row - 1)
        out.extend(p for p in self._doc_unit(start, head_end, name, sub_level, scope))
        children = []
        for k, h in enumerate(subs):
            sub_end = self._trim(h.row, subs[k + 1].row - 1 if k + 1 < len(subs) else end)
            children.extend(self._doc_unit(h.row, sub_end, h.name or "(untitled)", sub_level,
                                           own_scope))
        out.extend(self._merge(children))
        for piece in out:
            piece.final = True
        return out

    def _doc_paragraphs(self, start: int, end: int, scope: list[str],
                        named: bool) -> list[_Piece]:
        pieces = []
        reserve = self._reserve(scope, [])
        for s, e in markdown.paragraph_blocks(self.lines, start, end, self.fences):
            tokens = self._tokens(s, e)
            if tokens + reserve <= self.s.max_tokens:
                pieces.append(_Piece(s, e, "block", scope, [], tokens=tokens))
            else:
                self.window_reasons["oversized paragraph"] += 1
                pieces.extend(_Piece(ws, we, "window", scope, [], tokens=self._tokens(ws, we),
                                     final=True)
                              for ws, we in self._window_ranges(s, e, reserve))
        packed = self._pack(pieces)
        for piece in packed:
            piece.final = True
        return self._label_parts(packed) if named else packed

    def _has_embed_body(self, start: int, end: int) -> bool:
        return any(line is not None and line.strip()
                   for line in self.embed_lines[start:end + 1])

    def _attach_empty(self, pieces: list[_Piece]) -> list[_Piece]:
        """A chunk must never embed an empty body (e.g. a badge-only intro): attach such a
        piece to the previous one, or to the next one at the start of the file."""
        out, carry = [], None
        for piece in pieces:
            if not self._has_embed_body(piece.start, piece.end):
                if out:
                    out[-1].end = piece.end
                elif carry is None:
                    carry = piece.start
                continue
            if carry is not None:
                piece.start, carry = carry, None
            out.append(piece)
        if carry is not None:  # nothing embeddable at all: keep one chunk for coverage
            out.append(replace(pieces[0], start=carry, end=pieces[-1].end))
        return out

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
            if self.s.window_prefer_blank_lines and j + 1 <= end:
                # Stopped by the budget: end at the last blank line in the final quarter, so
                # the window breaks between functions/paragraphs rather than inside one.
                floor = i + (j - i) * 3 // 4
                for k in range(j, floor, -1):
                    if not self.lines[k].strip():
                        j = k - 1
                        break
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
            i, n = piece.part
            return f"{base or self.root} (part {i}/{n})" if n else f"{base or self.root} (part {i})"
        if piece.names:
            return " > ".join(piece.scope + [self._names_label(piece.names)])
        return base or self.root

    def _build(self, piece: _Piece, start: int, end: int) -> Chunk:
        content = "\n".join(self.lines[start:end + 1])
        code = content if self.embed_lines is self.lines else "\n".join(
            line for line in self.embed_lines[start:end + 1] if line is not None)
        breadcrumb = self._breadcrumb(piece)
        body = "\n".join(piece.context) + "\n...\n" + code if piece.context else code
        if piece.outline:
            body += "\n\n" + piece.outline
        embed_text = self._head(breadcrumb) + body
        return Chunk(self.path, start + 1, end + 1, piece.kind, self._names_label(piece.names),
                     breadcrumb, content, embed_text, self.count(embed_text))

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
