from dataclasses import replace

from helpers import check_invariants, fake_count

from codeask import markdown
from codeask.chunker import ChunkSettings, chunk_file

NO_MERGE = ChunkSettings(min_tokens=1)


def chunks_of(text, path="README.md", settings=NO_MERGE):
    result = chunk_file(path, text, fake_count, settings)
    check_invariants(text, result, settings.max_tokens)
    return result


def summary(result):
    return [(c.start_line, c.end_line, c.kind, c.breadcrumb) for c in result.chunks]


# ---------- scanner ----------
def heads(text, rst=False):
    lines = text.split("\n")
    fences = [] if rst else markdown.fence_ranges(lines)  # as the chunker does
    fenced = {r for a, b in fences for r in range(a, b + 1)}
    return [(h.row + 1, h.level, h.name) for h in markdown.headings(lines, rst, fenced)]


def test_atx_and_setext_headings_outside_fences():
    text = ("# Title\n\nIntro\n\n## Install\n\n```bash\n# not a heading\n```\n\n"
            "Usage\n=====\n\nMore\n\nNotes\n-----\n\n### Deep\n")
    assert heads(text) == [(1, 1, "Title"), (5, 2, "Install"), (11, 1, "Usage"),
                           (16, 2, "Notes"), (19, 3, "Deep")]


def test_rst_levels_follow_first_appearance():
    text = "Title\n=====\n\nSub\n---\n\nOther\n=====\n\nDeeper\n~~~~~~\n"
    assert heads(text, rst=True) == [(1, 1, "Title"), (4, 2, "Sub"), (7, 1, "Other"),
                                     (10, 3, "Deeper")]


def test_rst_underline_rules():
    # Too short, internal spaces (a simple table), and indented: none are headings.
    text = "Long title\n===\n\nA\n== ==\n\n  Indented\n  ========\n"
    assert heads(text, rst=True) == []


def test_front_matter_is_not_a_heading():
    text = "---\ntitle: Docs\n---\n\n# Real\n"
    lines = text.split("\n")
    skip = set(range(markdown.front_matter_end(lines) + 1))
    assert [h.name for h in markdown.headings(lines, False, skip)] == ["Real"]


def test_noise_lines():
    assert markdown.is_noise("[![CI](https://x/badge.svg)](https://x/actions)")
    assert markdown.is_noise("![logo](logo.png) ![pypi](https://img.shields.io/pypi/v/x)")
    assert markdown.is_noise('<p align="center"><img src="logo.png" width="200"></p>')
    assert markdown.is_noise("[docs]: https://example.com/docs")
    assert not markdown.is_noise("See the [docs](https://example.com) for details.")
    assert not markdown.is_noise('<a href="x">Read the docs</a>')


# ---------- chunking ----------
README = """\
[![CI](https://img.shields.io/ci.svg)](https://ci.example.com)
[![PyPI](https://img.shields.io/pypi.svg)](https://pypi.org/x)

# Project

A tool that does things.

## Install

pip install project

## Usage

Call `run()`.

### Options

Use `--fast`.

[docs]: https://example.com/docs
"""


def test_sections_breadcrumbs_and_badge_only_intro_attaches():
    result = chunks_of(README)
    assert result.method == "ast"
    # The badge-only intro (lines 1-2) has no embeddable text, so it joins the next section.
    assert summary(result) == [
        (1, 6, "section", "Project"),
        (8, 10, "section", "Project > Install"),
        (12, 20, "section", "Project > Usage"),  # H3 stays inside its H2
    ]


def test_noise_is_stripped_from_embed_text_only():
    first, _, usage = chunks_of(README).chunks
    assert "shields.io" in first.content  # displayed and cited as in the file
    assert "shields.io" not in first.embed_text  # but never embedded
    assert "[docs]: https" in usage.content and "[docs]: https" not in usage.embed_text


def test_no_chunk_has_an_empty_embeddable_body():
    text = "# Title\n\nText.\n\n## Badges\n\n![a](a.svg)\n![b](b.svg)\n"
    for c in chunks_of(text).chunks:
        body = c.embed_text.split("\n\n", 1)[1]
        assert body.strip() and "a.svg" not in body


def test_small_sections_merge_with_defaults():
    result = chunks_of(README, settings=ChunkSettings())
    (chunk,) = result.chunks
    assert chunk.kind == "merged" and chunk.name == "Project, Install, Usage"


TIGHT = ChunkSettings(max_tokens=60, target_max=30, target_min=15, min_tokens=1)


def test_over_cap_section_splits_at_the_next_heading_level():
    options = "\n\n".join(f"Option {i} does something useful." for i in range(4))
    text = (f"## Usage\n\nCall run() with options.\n\n### Flags\n\n{options}\n\n"
            f"### Env\n\nSet APP_MODE.\n")
    result = chunks_of(text, settings=TIGHT)
    crumbs = [c.breadcrumb for c in result.chunks]
    assert crumbs[0] == "Usage"  # the head: heading + intro, keeps the section's name
    assert any(c.startswith("Usage > Flags") for c in crumbs)
    assert "Usage > Env" in crumbs


def test_over_cap_section_without_subsections_splits_by_paragraph_fences_whole():
    paras = "\n\n".join(f"Paragraph {i} explains one more detail." for i in range(6))
    fence = "```python\nx = 1\n\ny = 2\n```"
    text = f"## Guide\n\n{paras}\n\n{fence}\n\nDone.\n"
    result = chunks_of(text, settings=TIGHT)
    assert all(c.breadcrumb.startswith("Guide (part ") for c in result.chunks)
    with_fence = [c for c in result.chunks if "```python" in c.content]
    assert len(with_fence) == 1 and with_fence[0].content.count("```") == 2  # never split


def test_over_cap_line_is_truncated_in_embed_text_not_skipped():
    long_line = "word " * 400  # ~500 fake tokens, over a 300 cap
    text = f"# Title\n\n{long_line}\n\nAfter.\n"
    settings = ChunkSettings(max_tokens=300, target_max=200, target_min=100, min_tokens=1)
    result = chunks_of(text, settings=settings)
    assert result.method == "ast" and result.truncated_lines == 1
    holder = next(c for c in result.chunks if long_line.strip() in c.content)
    assert holder.embed_text.count("word") < 400  # truncated for embedding only


def test_rst_tilde_underline_is_not_a_fence():
    # Regression: "~~~~" opened a Markdown fence and hid every later reST heading.
    text = "Guide\n=====\n\nPart\n~~~~\n\nText.\n\nLater\n=====\n\nMore.\n"
    result = chunks_of(text, path="docs/guide.rst")
    # "~" is the second underline style to appear, so Part is level 2, under Guide.
    assert [c.breadcrumb for c in result.chunks] == ["Guide", "Guide > Part", "Later"]


def test_rst_document_sections():
    text = "Flask\n=====\n\nA framework.\n\nQuickstart\n----------\n\nRun it.\n"
    result = chunks_of(text, path="docs/index.rst")
    assert summary(result) == [(1, 4, "section", "Flask"), (6, 9, "section", "Flask > Quickstart")]


def test_front_matter_is_not_embedded():
    text = "---\nlayout: page\n---\n\n# Home\n\nWelcome.\n"
    (chunk,) = chunks_of(text).chunks
    assert chunk.start_line == 1 and "layout" not in chunk.embed_text


def test_doc_without_headings():
    result = chunks_of("Just a paragraph.\n\nAnother one.\n")
    assert {c.kind for c in result.chunks} == {"intro"}
    assert result.chunks[0].breadcrumb == "<document>"


# ---------- windows: polish and labels ----------
GO = "".join(f"func f{i}(x int) int {{\n\treturn x + {i}\n}}\n\n" for i in range(20))
WIN = ChunkSettings(max_tokens=60, target_max=30, target_min=15)


def test_windows_prefer_ending_at_blank_lines():
    polished = chunks_of(GO, path="main.go", settings=WIN)
    naive = chunks_of(GO, path="main.go", settings=replace(WIN, window_prefer_blank_lines=False))
    # Polished windows end on a function's closing brace, never mid-function.
    assert all(c.content.rstrip().endswith("}") for c in polished.chunks)
    assert any(not c.content.rstrip().endswith("}") for c in naive.chunks)


def test_whole_file_window_labels_have_no_total():
    result = chunks_of(GO, path="main.go", settings=WIN)
    assert [c.breadcrumb for c in result.chunks] == \
        [f"<module> (part {i})" for i in range(1, len(result.chunks) + 1)]
    (single,) = chunks_of("package main\n", path="main.go").chunks
    assert single.breadcrumb == "<module>"
