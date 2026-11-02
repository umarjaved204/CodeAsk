"""The ask() pipeline offline: fake store and LLM. Grounding rules (Q3, Q9, Q23)."""

from codeask.ask import ask, public_view
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

    def chat(self, messages):
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


def test_public_view_never_exposes_raw_answer_context_usage_or_headers():
    assert set(public_view(run("X [a.py:2-3]."))) == {
        "grounded", "answer", "citations", "possibly_relevant", "model", "prompt_version"}
