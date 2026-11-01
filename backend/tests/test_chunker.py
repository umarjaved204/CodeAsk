from dataclasses import replace

from helpers import check_invariants, fake_count

from codeask.chunker import ChunkSettings, chunk_file

DEFAULT = ChunkSettings()
NO_MERGE = ChunkSettings(min_tokens=1)  # every unit stands alone

SAMPLE = '''\
"""Module docstring."""
import os

MAX = 10  # constant


# Helper comment.
def helper(x):
    return x + 1


@decorator
def decorated():
    pass


class Signer:
    """Doc."""

    default = "x"

    def sign(self, value):
        return value
'''


def chunks_of(text, settings=DEFAULT, path="m.py", count=fake_count):
    result = chunk_file(path, text, count, settings)
    check_invariants(text, result, settings.max_tokens)
    return result


def summary(result):
    return [(c.start_line, c.end_line, c.kind, c.breadcrumb) for c in result.chunks]


# ---------- units, comments, shared lines ----------
def test_units_comments_decorators_and_shared_lines():
    result = chunks_of(SAMPLE, NO_MERGE)
    assert result.method == "ast"
    assert summary(result) == [
        (1, 1, "module", "<module>"),
        (2, 2, "module", "<module>"),
        (4, 4, "module", "<module>"),  # `MAX = 10  # constant`: two nodes, one line, one chunk
        (7, 9, "function", "helper"),  # the comment directly above attaches
        (12, 14, "function", "decorated"),  # decorator included
        (17, 23, "class", "Signer"),  # fits, so kept whole
    ]


def test_detached_comment_does_not_attach():
    text = "# Section header\n\ndef f():\n    return 1\n"
    assert summary(chunks_of(text, NO_MERGE)) == [
        (1, 1, "module", "<module>"), (3, 4, "function", "f")]


# ---------- merging ----------
def test_small_siblings_merge_like_with_like():
    result = chunks_of(SAMPLE)  # defaults: everything here is below min_tokens
    assert summary(result) == [
        (1, 4, "module", "<module>"),  # anonymous with anonymous
        (7, 23, "merged", "helper, decorated, Signer"),  # named with named
    ]
    assert result.chunks[1].name == "helper, decorated, Signer"


def test_merged_names_are_capped():
    text = "".join(f"def f{i}():\n    pass\n\n\n" for i in range(1, 8))
    (chunk,) = chunks_of(text).chunks
    assert chunk.kind == "merged"
    assert chunk.name == "f1, f2, f3, f4, f5 +2 more"


def test_units_at_or_above_min_stand_alone():
    body = "\n".join(f"    v{i} = compute_something_long({i})" for i in range(8))
    text = f"def a():\n{body}\n\n\ndef b():\n{body}\n"
    assert [c.breadcrumb for c in chunks_of(text).chunks] == ["a", "b"]


# ---------- classes over the cap ----------
SMALL = ChunkSettings(max_tokens=90, target_max=50, target_min=30, min_tokens=1,
                      outline_max_tokens=40)


def big_class(n_methods):
    methods = "\n".join(
        f"    def m{i}(self, value):\n"
        f"        result = transform_{i}(value)\n"
        f"        return result\n"
        for i in range(n_methods))
    return f'class Signer(Base):\n    """Doc."""\n\n    default = "x"\n\n{methods}'


def test_class_over_cap_splits_into_header_and_methods():
    result = chunks_of(big_class(4), SMALL)
    header, *methods = result.chunks
    assert (header.kind, header.breadcrumb, header.start_line, header.end_line) == \
        ("class_header", "Signer", 1, 4)
    assert "Members:\n  def m0(self, value):" in header.embed_text
    assert [m.breadcrumb for m in methods] == [f"Signer > m{i}" for i in range(4)]
    # Each method carries its enclosing class line as context.
    assert all("class Signer(Base):\n...\n" in m.embed_text for m in methods)


def test_class_outline_is_capped():
    result = chunks_of(big_class(20), replace(SMALL, outline_max_tokens=20))
    header = result.chunks[0]
    assert header.kind == "class_header"
    assert "more" in header.embed_text
    assert header.token_count <= SMALL.max_tokens


def test_header_over_cap_keeps_outline_on_first_part():
    docstring = "\n".join(f"    Line {i} of a long docstring about signing." for i in range(25))
    text = f'class Signer:\n    """\n{docstring}\n    """\n\n' + big_class(3).split("\n", 4)[4]
    result = chunks_of(text, SMALL)
    header = result.chunks[0]
    assert header.kind == "class_header"
    assert header.breadcrumb.startswith("Signer (part 1/")
    assert "Members:\n  def m0(self, value):" in header.embed_text
    assert [c.kind for c in result.chunks[1:]].count("class_header") == 0


# ---------- functions over the cap ----------
TINY = ChunkSettings(max_tokens=70, target_max=30, target_min=15, min_tokens=1)

BIG_FUNCTION = '''\
@cached
def big(x):
    """Docstring of big."""
    total = 0
    if x > 0:
        total = total + first_branch(x)
        total = total + more_work(x)
    elif x < 0:
        total = total - second_branch(x)
    else:
        total = fallback_value()
    for item in range(x):
        total += item
    else:
        total += 1
    try:
        risky_operation(total)
    except ValueError as error:
        handle_error(error)
    finally:
        cleanup_resources()
    return total
'''


def test_function_over_cap_splits_into_parts_with_context():
    result = chunks_of(BIG_FUNCTION, TINY)
    assert len(result.chunks) > 1
    n = len(result.chunks)
    assert [c.breadcrumb for c in result.chunks] == [f"big (part {i}/{n})" for i in range(1, n + 1)]
    assert all(c.kind == "part" for c in result.chunks)
    assert all("def big(x):" in c.embed_text for c in result.chunks)
    # Clause lines (elif/else/except/finally) are owned by exactly one chunk (invariants), and
    # pieces inside a compound statement also carry its header line.
    inside_try = next(c for c in result.chunks if "handle_error" in c.content)
    assert "    try:" in inside_try.embed_text or "    try:" in inside_try.content


def test_oversized_single_statement_falls_back_to_windows():
    items = "\n".join(f"        'key_{i}': value_number_{i}," for i in range(30))
    text = f"def config():\n    return {{\n{items}\n    }}\n"
    result = chunks_of(text, TINY)
    assert len(result.chunks) > 1
    assert all(c.breadcrumb.startswith("config (part ") for c in result.chunks)


def test_module_level_data_is_windowed():
    items = "\n".join(f"    'key_{i}': value_number_{i}," for i in range(30))
    result = chunks_of(f"TABLE = {{\n{items}\n}}\n", TINY)
    assert len(result.chunks) > 1
    assert {c.kind for c in result.chunks} == {"window"}


def test_exact_count_guard_resplits_when_estimates_drift():
    # A tokenizer that charges extra for long texts: per-line estimates under-count.
    def drifting(text):
        return fake_count(text) + (25 if len(text) > 200 else 0)
    settings = ChunkSettings(max_tokens=120, target_max=100, target_min=50, min_tokens=1)
    result = chunks_of(BIG_FUNCTION, settings, count=drifting)
    assert all(c.token_count <= 120 for c in result.chunks)


# ---------- skips and fallbacks ----------
def test_line_over_cap_skips_file():
    text = "x = '" + "a" * 400 + "'\n"
    result = chunk_file("m.py", text, fake_count, TINY)
    assert (result.chunks, result.method, result.skip_reason) == \
        ([], "skipped", "line exceeds token cap")


def test_syntax_error_falls_back_to_windows():
    result = chunks_of("def ok():\n    return 1\n\ndef broken(:\n    return 2\n")
    assert result.method == "fallback"
    assert {c.kind for c in result.chunks} == {"window"}


def test_unsupported_language_uses_windows():
    result = chunks_of("package main\n\nfunc main() {}\n", path="main.go")
    assert result.method == "windows"


def test_windows_mode_ignores_the_grammar():
    result = chunks_of(SAMPLE, replace(DEFAULT, mode="windows"))
    assert result.method == "windows"
    assert {c.kind for c in result.chunks} == {"window"}


def test_window_overlap_ablation():
    settings = ChunkSettings(mode="windows", max_tokens=40, target_max=20, target_min=10,
                             window_overlap_lines=1)
    result = chunk_file("m.py", BIG_FUNCTION, fake_count, settings)
    pairs = list(zip(result.chunks, result.chunks[1:]))
    # Multi-line windows share their last line with the next window (a one-line window can't).
    assert any(b.start_line <= a.end_line for a, b in pairs)
    assert all(b.start_line > a.start_line for a, b in pairs)  # always moves forward


# ---------- edge cases ----------
def test_empty_and_whitespace_files_give_no_chunks():
    for text in ("", "\n\n   \n"):
        result = chunk_file("m.py", text, fake_count)
        assert (result.chunks, result.method) == ([], "empty")


def test_no_trailing_newline():
    result = chunks_of("def f():\n    return 1")
    assert summary(result) == [(1, 2, "function", "f")]
    assert result.chunks[0].content == "def f():\n    return 1"


def test_comments_only_file():
    result = chunks_of("# one\n# two\n\n# three\n")
    assert {c.kind for c in result.chunks} == {"module"}


def test_single_unit_file():
    assert summary(chunks_of("class A:\n    x = 1\n")) == [(1, 2, "class", "A")]


def test_embed_text_format_and_flags():
    text = "def f():\n    return 1\n"
    (chunk,) = chunks_of(text).chunks
    assert chunk.embed_text == "File: m.py\nScope: f\n\ndef f():\n    return 1"
    (bare,) = chunks_of(text, replace(DEFAULT, include_path=False, include_scope=False)).chunks
    assert bare.embed_text == "def f():\n    return 1"
    (no_path,) = chunks_of(text, replace(DEFAULT, include_path=False)).chunks
    assert no_path.embed_text == "Scope: f\n\ndef f():\n    return 1"


# ---------- determinism and stability ----------
def three_functions(middle_body="    return compute(a, b, c)"):
    def fn(name, body):
        return (f"def {name}(a, b, c):\n"
                f'    """Long enough docstring to stay above the merge minimum."""\n'
                f"    first = prepare_input_values(a, b)\n"
                f"    second = combine_the_results(first, c)\n"
                f"    third = finalize_everything(second, first)\n"
                f"    fourth = validate_the_output(third, second)\n"
                f"{body}\n")
    return "\n\n".join([fn("alpha", "    return second"), fn("beta", middle_body),
                        fn("gamma", "    return second")])


def test_deterministic():
    assert chunks_of(BIG_FUNCTION, TINY) == chunks_of(BIG_FUNCTION, TINY)
    assert chunks_of(SAMPLE) == chunks_of(SAMPLE)


def test_body_edit_inside_one_unit_changes_exactly_one_chunk():
    before = {c.embed_text for c in chunks_of(three_functions()).chunks}
    after = {c.embed_text for c in chunks_of(three_functions("    return compute(c, b, a)")).chunks}
    assert len(before) == 3
    assert len(before - after) == 1 and len(after - before) == 1


def test_inserting_lines_above_changes_no_other_chunk():
    original = three_functions()
    shifted = "import extra_module\n\n\n" + original
    before = {c.embed_text for c in chunks_of(original).chunks}
    after = {c.embed_text for c in chunks_of(shifted).chunks}
    assert before <= after  # every old chunk is unchanged (embed_text has no line numbers)
