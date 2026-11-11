"""The ask() pipeline offline: fake store and LLM. Grounding rules (Q3, Q9, Q23)."""

from codeask.ask import ask, evidence, public_view
from codeask.llm import Reply

REPO = {"slug": "o/r", "url": "https://github.com/o/r", "commit_sha": "abc",
        "settings": {"space": "s"}}


def row(path, start, end):
    return {"path": path, "start_line": start, "end_line": end, "token_count": 10,
            "kind": "function", "breadcrumb": "f", "distance": 0.4,
            "content": "\n".join(f"line {i}" for i in range(start, end + 1))}


class FakeStore:
    def __init__(self, rows):
        self.rows = rows

    def search(self, slug, space, vector, k):
        return self.rows[:k]

    def file_chunks(self, slug, paths):
        return [r for r in self.rows if r["path"] in paths]


class FakeLLM:
    def __init__(self, text):
        self.text, self.messages = text, None

    def chat(self, messages, deadline=None):
        self.messages = messages
        return Reply(self.text, None, {}, {}, "m", 0.1, 0)


# a.py ranks 1st and 4th, so the distinct files by rank are a, b, c, d.
ROWS = [row("a.py", 1, 5), row("b.py", 1, 5), row("c.py", 1, 5), row("a.py", 20, 25),
        row("d.py", 1, 5)]


def run(text, rows=ROWS):
    return ask(FakeStore(rows), FakeLLM(text), REPO, "q?", [0.0])


def test_zero_valid_citations_is_ungrounded_and_the_text_is_withheld():
    result = run("It does X [z.py:1-2]. Not in the files otherwise.")
    assert not result["grounded"] and result["stats"]["unverified"] == 1
    assert result["raw_answer"].startswith("It does X")  # kept for eval
    view = public_view(result)
    assert view["grounded"] is False and view["answer"] is None and view["citations"] == []


def test_possibly_relevant_is_top_three_distinct_files_by_rank_with_permalinks():
    files = run("No citation at all.")["possibly_relevant"]
    assert [f["path"] for f in files] == ["a.py", "b.py", "c.py"]
    assert files[0] == {"path": "a.py", "start": 1, "end": 5,
                        "url": "https://github.com/o/r/blob/abc/a.py#L1-L5"}


def test_possibly_relevant_includes_retrieved_files_that_were_not_packed():
    big = {**row("big.py", 1, 5), "token_count": 5_000}  # over the budget: dropped
    result = run("No citation.", [big, *ROWS])
    assert not any(b.startswith("big.py") for b in result["blocks"])
    assert result["dropped"] == [("big.py:1-5", "budget")]
    assert result["possibly_relevant"][0]["path"] == "big.py"


def test_one_valid_citation_is_grounded_and_shown():
    result = run("It does X [a.py:2-3].")
    view = public_view(result)
    assert result["grounded"] and result["possibly_relevant"] == []
    assert view["answer"] == "It does X [1](cite:1)." and view["citations"][0]["valid"]


def test_mixed_valid_and_unverified_citations_keep_both():
    view = public_view(run("X [a.py:2-3], Y [z.py:1-2]."))
    assert view["grounded"]
    assert [c["valid"] for c in view["citations"]] == [True, False]


def test_public_view_never_exposes_raw_answer_usage_or_headers():
    assert set(public_view(run("X [a.py:2-3]."))) == {
        "grounded", "answer", "citations", "blocks", "possibly_relevant", "model",
        "prompt_version"}


# ---------- evidence blocks for the code panel (Q30) ----------
def test_only_blocks_with_a_valid_citation_are_sent_once_with_a_block_index():
    view = public_view(run("X [a.py:2-3], [a.py:4-5]. Y [c.py:1-2]. Z [z.py:1-2]."))
    assert [(b["path"], b["start"], b["end"]) for b in view["blocks"]] == [
        ("a.py", 1, 5), ("c.py", 1, 5)]  # b.py, d.py and a.py:20-25 were supplied, not cited
    assert [c["block"] for c in view["citations"]] == [0, 0, 1, None]  # z.py: unverified


def test_blocks_hold_raw_lines_exactly_as_supplied():
    (block,) = public_view(run("X [a.py:2-3]."))["blocks"]
    assert block["content"] == "\n".join(f"line {i}" for i in range(1, 6))  # no "1| " prefix


def test_ungrounded_answers_send_no_blocks():
    view = public_view(run("Probably HMAC [z.py:1-2]."))
    assert view["blocks"] == [] and view["citations"] == []


def test_blocks_past_the_size_cap_are_left_out_and_their_citations_get_no_block():
    context = [{"path": "a.py", "start": 1, "end": 2, "content": "x" * 30},
               {"path": "b.py", "start": 1, "end": 2, "content": "y" * 30}]
    citations = [{"n": 1, "path": "a.py", "start": 1, "end": 2, "valid": True},
                 {"n": 2, "path": "b.py", "start": 1, "end": 1, "valid": True}]
    blocks, cited = evidence(context, citations, max_chars=40)
    assert [b["path"] for b in blocks] == ["a.py"]
    assert [c["block"] for c in cited] == [0, None]


# ---------- pre-generated answer fixture (slice 3) ----------
def test_fixture_records_how_it_was_made_and_starts_ungraded():
    from datetime import datetime, timezone

    from codeask import config
    from codeask.ask import fixture

    result = run("X [a.py:2-3].")
    record = fixture(result, REPO, "q?", "qwen/qwen3.8-27b", 2, "attempt 1 printed only",
                     datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc))
    assert record["grade"] is None  # filled in by the author, never by the script
    assert (record["attempt"], record["attempt_note"]) == (2, "attempt 1 printed only")
    assert record["generated_at"] == "2026-11-03T12:00:00+00:00"
    assert record["commit_sha"] == "abc" and record["prompt_version"] == result["prompt_version"]
    assert record["generation"] == {"temperature": config.ANSWER_TEMPERATURE,
                                    "max_completion_tokens": config.ANSWER_MAX_TOKENS,
                                    "model_options": {"reasoning_effort": "none"}}
    assert record["packer"]["budget"] == config.CONTEXT_BUDGET_TOKENS
    assert record["response"] == public_view(result)  # exactly what the API would send
    assert "raw_answer" not in record and "context" not in record
