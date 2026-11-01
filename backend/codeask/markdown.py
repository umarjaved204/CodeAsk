"""Line scanning for Markdown and reStructuredText: fences, headings, paragraphs, and the
lines that are noise for an embedding (badges, reference-link tails, front matter).

A scanner, not a grammar: docs only need section boundaries, and a line scanner that tracks
code fences gets those right without another dependency. All functions work on 0-based rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DOC_EXT = (".md", ".markdown", ".rst")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*#*[ \t]*$")
# Lines with no prose for an embedding: badges/images, HTML-tag-only lines, link definitions.
BADGE = re.compile(r"^(\s*\[?!\[[^\]]*\]\([^)]*\)\]?(\([^)]*\))?)+\s*$")
HTML_ONLY = re.compile(r"^(\s*<[^>]+>)+\s*$")
REF_LINK = re.compile(r"^ {0,3}\[[^\]]+\]:\s*\S+")
LIST_ITEM = re.compile(r"^([-*+]|\d+[.)])\s")
UNDERLINE_CHARS = set("=-~^\"'`#*+<>:._")


@dataclass(frozen=True)
class Heading:
    row: int  # the title row
    level: int  # 1 = top
    name: str


def is_noise(line: str) -> bool:
    return bool(BADGE.match(line) or HTML_ONLY.match(line) or REF_LINK.match(line))


def front_matter_end(lines: list[str]) -> int:
    """Last row of YAML front matter (--- ... ---) at the top of a Markdown file, or -1."""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                return i
    return -1


def fence_ranges(lines: list[str], start: int = 0) -> list[tuple[int, int]]:
    """(first, last) rows of each ``` / ~~~ code fence, fence lines included. An unclosed
    fence runs to the end of the file (as Markdown renders it)."""
    out, opening, first = [], None, 0
    for i in range(start, len(lines)):
        m = FENCE.match(lines[i])
        if opening is None:
            if m:
                opening, first = m.group(1), i
        elif m and m.group(1)[0] == opening[0] and len(m.group(1)) >= len(opening) \
                and lines[i].strip() == m.group(1):
            out.append((first, i))
            opening = None
    if opening is not None:
        out.append((first, len(lines) - 1))
    return out


def _is_underline(line: str) -> bool:
    s = line.strip()  # one repeated character: an internal space would add " " to the set
    return len(s) >= 3 and len(set(s)) == 1 and s[0] in UNDERLINE_CHARS \
        and not line[:1].isspace()


def headings(lines: list[str], rst: bool, skip: set[int]) -> list[Heading]:
    """Headings outside `skip` (fenced rows, front matter).

    Markdown: ATX (`#`..`######`) and setext (`Title` + `===` = level 1, `---` = level 2).
    reST: `Title` + an underline of one repeated character (no internal spaces) at least as
    long as the title; levels follow the order in which underline styles first appear. An
    overline above the title is tolerated but stays with the previous section.
    """
    out, rst_levels = [], {}
    for i, line in enumerate(lines):
        if i in skip:
            continue
        if not rst:
            m = ATX.match(line)
            if m:
                out.append(Heading(i, len(m.group(1)), (m.group(2) or "").strip()))
                continue
        if i + 1 >= len(lines) or (i + 1) in skip or not line.strip() or line[:1].isspace():
            continue
        if _is_underline(line) or LIST_ITEM.match(line):
            continue
        prev = lines[i - 1] if i else ""
        if prev.strip() and not _is_underline(prev):
            continue  # a title starts a block (after a blank line, or under an overline)
        under = lines[i + 1]
        if not _is_underline(under):
            continue
        ch = under.strip()[0]
        if rst:
            if len(under.strip()) < len(line.strip()):
                continue
            level = rst_levels.setdefault(ch, len(rst_levels) + 1)
        else:
            if ch not in "=-":
                continue
            level = 1 if ch == "=" else 2
        out.append(Heading(i, level, line.strip()))
    return out


def paragraph_blocks(lines: list[str], start: int, end: int,
                     fences: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Blank-line separated blocks in [start, end]; a code fence is always one block."""
    fence_at = {first: last for first, last in fences}
    fenced = {r for first, last in fences for r in range(first, last + 1)}
    out, i = [], start
    while i <= end:
        if not lines[i].strip() and i not in fenced:
            i += 1
            continue
        if i in fence_at:
            j = min(fence_at[i], end)
        else:
            j = i
            while j + 1 <= end and lines[j + 1].strip() and (j + 1) not in fence_at:
                j += 1
        out.append((i, j))
        i = j + 1
    return out
