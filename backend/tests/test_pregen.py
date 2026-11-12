"""Pre-generation (slice 5, build step 4) offline: fake store, LLM and clock; files in tmp_path.
The rules under test: no re-rolls, at most 2 re-runs of a run with no answer text (Q50), the
token guard and pacing (Q53), and the frozen, pinned questions file (Q48, Q52)."""

import json
import os
from datetime import datetime, timezone

import pytest

from codeask import config
from codeask.askqueue import Pacer
from codeask.llm import GroqError, RateLimited, Reply
from codeask.pregen import Paths, Stop, check_record, generate, load_questions, verify

SHA = "a" * 40
REPO = {"slug": "o/r", "url": "https://github.com/o/r", "commit_sha": SHA,
        "settings": {"space": "s"}}
NOW = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)
ROWS = [{"path": "a.py", "start_line": 1, "end_line": 5, "token_count": 10, "kind": "function",
         "breadcrumb": "f", "distance": 0.4,
         "content": "\n".join(f"line {i}" for i in range(1, 6))}]


class FakeStore:
    def search(self, slug, space, vector, k):
        return ROWS

    def file_chunks(self, slug, paths):
        return ROWS


class FakeLLM:
    """Plays its outcomes in order: an exception is raised, a number is the answer's
    completion tokens."""

    model = config.GROQ_MODEL

    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def chat(self, messages, deadline=None):
        self.calls.append(deadline)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        usage = {"prompt_tokens": 2_000, "completion_tokens": outcome,
                 "total_tokens": 2_000 + outcome}
        return Reply("It does X [a.py:1-2].", None, usage, {}, self.model, 0.5, 0)


class Clock:
    def __init__(self):
        self.t = 1_000.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def entries(*ids):
    return [({"id": i, "question": f"How does {i} work?"}, [0.0]) for i in ids]


def run(tmp_path, llm, ids=("q1",), max_tokens=100_000, clock=None):
    clock = clock or Clock()
    paths = Paths("o/r", root=tmp_path)
    lines = []
    total = generate(entries(*ids), REPO, paths, FakeStore(), llm, Pacer(), max_tokens,
                     clock=clock, sleep=clock.sleep, wall=lambda: NOW, out=lines.append)
    return paths, total, lines


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_an_answer_is_stored_with_its_settings_runs_and_raw_result(tmp_path):
    paths, total, _ = run(tmp_path, FakeLLM(300))
    record = read(tmp_path / "frontend/data/examples/o__r/q1.json")
    assert record["question_id"] == "q1" and record["question"] == "How does q1 work?"
    assert record["commit_sha"] == SHA and record["generated_at"] == "2026-11-13T10:00:00+00:00"
    assert record["attempt"] == 1 and record["attempt_note"] is None and record["grade"] is None
    assert record["response"]["grounded"] is True
    assert record["runs"] == [{"id": "q1", "at": "2026-11-13T10:00:00+00:00",
                               "outcome": "answered", "tokens": 2_300, "estimated": False,
                               "error": None}]
    raw = read(tmp_path / "eval/results/m2d_raw/o__r/q1.json")
    assert raw["raw_answer"] == "It does X [a.py:1-2]." and raw["context"]
    assert total == 2_300 and paths.stored("q1") and not paths.stored("q2")


def test_each_question_gets_the_api_deadline(tmp_path):
    llm, clock = FakeLLM(300), Clock()
    run(tmp_path, llm, clock=clock)
    assert llm.calls == [clock.t + config.ASK_DEADLINE_S]


def test_an_error_with_no_answer_text_is_re_run_and_counted(tmp_path):
    llm = FakeLLM(GroqError("Groq 503: unavailable", 503), 300)
    paths, total, _ = run(tmp_path, llm)
    record = read(tmp_path / "frontend/data/examples/o__r/q1.json")
    assert [r["outcome"] for r in record["runs"]] == ["error", "answered"]
    assert record["runs"][0]["error"] == "GroqError: Groq 503: unavailable"
    assert record["runs"][0]["tokens"] == config.UNKNOWN_OUTCOME_TOKENS  # Groq was called
    assert record["attempt"] == 1 and "1 earlier run(s)" in record["attempt_note"]
    assert total == config.UNKNOWN_OUTCOME_TOKENS + 2_300


def test_a_third_error_stops_the_run_and_the_count_survives_a_restart(tmp_path):
    errors = [GroqError("Groq 500: x", 500) for _ in range(3)]
    with pytest.raises(Stop, match="q1 ended in an error 3 times"):
        run(tmp_path, FakeLLM(*errors))
    assert not (tmp_path / "frontend/data/examples/o__r/q1.json").exists()
    llm = FakeLLM(300)
    with pytest.raises(Stop, match="3 times"):  # a new run doesn't reset the count
        run(tmp_path, llm)
    assert llm.calls == []


def test_an_ungrounded_answer_is_still_the_attempt(tmp_path):
    class NoCitation(FakeLLM):
        def chat(self, messages, deadline=None):
            reply = super().chat(messages, deadline)
            return Reply("I can't tell from these files.", None, reply.usage, {}, self.model,
                         0.5, 0)

    _, _, lines = run(tmp_path, NoCitation(300))
    record = read(tmp_path / "frontend/data/examples/o__r/q1.json")
    assert record["response"]["grounded"] is False and len(record["runs"]) == 1
    assert "NOT GROUNDED" in lines[0]


def test_the_token_guard_stops_before_a_question_that_could_pass_it(tmp_path):
    llm = FakeLLM(300, 300)
    limit = 2_300 + config.QUESTION_RESERVE_TOKENS - 1
    with pytest.raises(Stop, match="q2 could pass --max-tokens"):
        run(tmp_path, llm, ids=("q1", "q2"), max_tokens=limit)
    assert len(llm.calls) == 1


def test_failed_runs_count_towards_the_token_guard(tmp_path):
    llm = FakeLLM(GroqError("Groq 500: x", 500), 300)
    with pytest.raises(Stop, match="could pass"):
        run(tmp_path, llm, max_tokens=config.UNKNOWN_OUTCOME_TOKENS
            + config.QUESTION_RESERVE_TOKENS - 1)
    assert len(llm.calls) == 1


def test_it_waits_for_the_output_token_window_instead_of_refusing(tmp_path):
    clock = Clock()
    run(tmp_path, FakeLLM(500, 300), ids=("q1", "q2"), clock=clock)
    # 500 recent output tokens + the next question's 600 > 1,000 a minute: wait it out.
    assert clock.slept and sum(clock.slept) == pytest.approx(config.OUTPUT_WINDOW_S)
    assert (tmp_path / "frontend/data/examples/o__r/q2.json").exists()


def test_groqs_daily_limit_stops_the_run(tmp_path):
    llm = FakeLLM(RateLimited("429", config.DAILY_BLOCK_MIN_RETRY_S + 1, {}), 300)
    with pytest.raises(Stop, match="daily limit"):
        run(tmp_path, llm)
    assert len(llm.calls) == 1


def test_a_bug_is_not_re_run(tmp_path):
    with pytest.raises(KeyError):
        run(tmp_path, FakeLLM(KeyError("x"), 300))
    assert not (tmp_path / "eval/results/m2d_runs_o__r.jsonl").exists()


def questions_file(tmp_path, **changes):
    data = {"repo": "o/r", "commit_sha": SHA, "confirmed": {"date": "2026-11-12"},
            "questions": [], **changes}
    path = tmp_path / "q.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_questions_accepts_a_confirmed_pinned_file(tmp_path):
    assert load_questions(questions_file(tmp_path), REPO, {"o/r": SHA})["repo"] == "o/r"


@pytest.mark.parametrize("changes, pins, message", [
    ({"confirmed": None}, {"o/r": SHA}, "not confirmed"),
    ({"commit_sha": "b" * 40}, {"o/r": SHA}, "commits differ"),
    ({}, {"o/r": "b" * 40}, "commits differ"),
    ({}, {}, "commits differ"),
    ({"repo": "x/y"}, {"o/r": SHA}, "the file is for x/y"),
])
def test_load_questions_refuses(tmp_path, changes, pins, message):
    with pytest.raises(Stop, match=message):
        load_questions(questions_file(tmp_path, **changes), REPO, pins)


# ---------- verify (build step 5, Q51): stored blocks against the real files ----------
def checkout(tmp_path):
    root = tmp_path / "clone"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_bytes(b"one\ntwo\nthree\nfour\n")
    return root


def answer(*blocks, sha=SHA):
    return {"commit_sha": sha, "response": {"blocks": [
        {"path": p, "start": s, "end": e, "content": c} for p, s, e, c in blocks]}}


def test_blocks_equal_to_the_file_lines_pass(tmp_path):
    root = checkout(tmp_path)
    assert check_record(answer(("src/a.py", 2, 3, "two\nthree"), ("src/a.py", 1, 1, "one")),
                        root, SHA) == []


def test_crlf_and_a_bom_are_read_as_ingest_reads_them(tmp_path):
    root = checkout(tmp_path)
    (root / "src" / "w.py").write_bytes(b"\xef\xbb\xbfone\r\ntwo\r\n")
    assert check_record(answer(("src/w.py", 1, 2, "one\ntwo")), root, SHA) == []


@pytest.mark.parametrize("block, problem", [
    (("src/a.py", 2, 3, "two\nTHREE"), "content differs"),
    (("src/a.py", 2, 3, "two\nthree\n"), "content differs"),  # exact: no trailing newline
    (("src/a.py", 4, 9, "four"), "outside the file"),
    (("src/a.py", 0, 1, "one"), "outside the file"),
    (("src/b.py", 1, 1, "one"), "file missing"),
    (("../clone/src/a.py", 1, 1, "one"), "unsafe"),
    (("src/./a.py", 1, 1, "one"), "unsafe"),
    (("src\a.py", 1, 1, "one"), "unsafe"),
    (("/src/a.py", 1, 1, "one"), "unsafe"),
    (("src", 1, 1, "one"), "unsafe"),  # a directory
])
def test_a_wrong_block_is_a_problem(tmp_path, block, problem):
    (found,) = check_record(answer(block), checkout(tmp_path), SHA)
    assert problem in found


def test_a_symlink_is_never_followed(tmp_path):
    root = checkout(tmp_path)
    try:
        os.symlink(root / "src" / "a.py", root / "src" / "link.py")
    except OSError:
        pytest.skip("creating symlinks needs Developer Mode or admin on Windows")
    (found,) = check_record(answer(("src/link.py", 1, 1, "one")), root, SHA)
    assert "unsafe" in found


def test_an_answer_for_another_commit_fails(tmp_path):
    (found,) = check_record(answer(("src/a.py", 1, 1, "one"), sha="b" * 40),
                            checkout(tmp_path), SHA)
    assert "answer is for bbbbbbb" in found


def test_verify_writes_the_result_into_each_answer(tmp_path):
    root, paths = checkout(tmp_path), Paths("o/r", root=tmp_path)
    paths.answers.mkdir(parents=True)
    good = {"question": "g?", **answer(("src/a.py", 1, 2, "one\ntwo"))}
    bad = {"question": "b?", **answer(("src/a.py", 1, 2, "one\n2"))}
    (paths.answers / "q1.json").write_text(json.dumps(good), encoding="utf-8")
    (paths.answers / "q2.json").write_text(json.dumps(bad), encoding="utf-8")
    results = verify(paths, root, SHA, NOW)
    assert results == {"q1": [], "q2": ["src/a.py:1-2: content differs from the file"]}
    q1, q2 = read(paths.answers / "q1.json"), read(paths.answers / "q2.json")
    assert q1["lines_check"] == {"ok": True, "commit_sha": SHA,
                                 "checked_at": "2026-11-13T10:00:00+00:00", "blocks": 1,
                                 "problems": []}
    assert q1["question"] == "g?" and q2["lines_check"]["ok"] is False


# ---------- export (build step 7): pass and flagship computed from the grade ----------
GOOD_GRADE = {"correct": "correct", "grounded": "yes", "citations_valid": "3/3",
              "unsupported": "none", "omission": "none", "reviewer": "claude",
              "date": "2026-11-13", "note": ""}


def stored(qid, valid=(True, True, True), completion=300, lines_ok=True, sha=SHA, graded=True,
           **grade):
    return {"question_id": qid, "question": f"How does {qid} work?", "commit_sha": sha,
            "usage": {"completion_tokens": completion},
            "grade": {**GOOD_GRADE, **grade} if graded else None,
            "lines_check": {"ok": lines_ok},
            "response": {"grounded": any(valid),
                         "citations": [{"n": i, "valid": v} for i, v in enumerate(valid, 1)]}}


def frozen(*ids):
    return {"repo": "o/r", "commit_sha": SHA,
            "questions": [{"id": i, "question": f"How does {i} work?"} for i in ids]}


def export(records, ids=("q1", "q2", "q3"), pins=(SHA, SHA)):
    from codeask.pregen import build_index
    return build_index(frozen(*ids), records, list(pins), NOW)


def test_the_first_passing_answer_that_meets_the_flagship_rule_leads(tmp_path):
    index, left_out = export({"q1": stored("q1", correct="incomplete"), "q2": stored("q2"),
                              "q3": stored("q3", omission="minor")})
    assert index["flagship"] == "q2" and index["flagship_note"] is None
    assert [q["id"] for q in index["questions"]] == ["q2", "q1", "q3"]
    assert index["questions"][0] == {"id": "q2", "question": "How does q2 work?"}
    assert index["commit_sha"] == SHA and index["exported_at"] == "2026-11-13T10:00:00+00:00"
    assert left_out == []


@pytest.mark.parametrize("record, reason", [
    (stored("q1", correct="incomplete"), "graded incomplete"),
    (stored("q1", omission="material"), "a material omission"),
    (stored("q1", valid=(True, True)), "2 valid citations"),
    (stored("q1", completion=config.ANSWER_MAX_TOKENS), "truncated"),
])
def test_with_no_qualifying_answer_the_first_passing_leads_with_the_reason(record, reason):
    index, _ = export({"q1": record}, ids=("q1",))
    assert index["flagship"] == "q1" and reason in index["flagship_note"]


@pytest.mark.parametrize("record", [
    stored("q2", correct="incorrect"),
    stored("q2", unsupported="load-bearing"),
    stored("q2", grounded="no"),
    stored("q2", valid=(True, False, True)),
    stored("q2", valid=(False,)),
])
def test_an_answer_that_does_not_pass_is_left_out(record):
    index, left_out = export({"q1": stored("q1"), "q2": record})
    assert [q["id"] for q in index["questions"]] == ["q1"]
    assert left_out == ["q3: not generated yet",
                        "q2: does not pass (Q50); step 6 moves it to failures"]


def test_minor_unsupported_claims_still_pass():
    index, _ = export({"q1": stored("q1", unsupported="minor")}, ids=("q1",))
    assert index["flagship"] == "q1"


@pytest.mark.parametrize("records, pins, message", [
    ({"q1": stored("q1")}, (SHA, "b" * 40), "pins differ"),
    ({"q1": stored("q1", sha="b" * 40)}, (SHA, SHA), "answer is for bbbbbbb"),
    ({"q1": stored("q1", lines_ok=False)}, (SHA, SHA), "lines_check is not ok"),
    ({"q1": stored("q1", graded=False)}, (SHA, SHA), "no grade"),
    ({"q1": stored("q1", omission="slight")}, (SHA, SHA), "grade.omission is 'slight'"),
    ({"q1": {**stored("q1"), "question_id": "q9"}}, (SHA, SHA), "answers q9"),
    ({"q1": {**stored("q1"), "question": "Reworded?"}}, (SHA, SHA), "differs from the frozen"),
    ({"q1": stored("q1", correct="incorrect")}, (SHA, SHA), "no passing answer"),
])
def test_export_refuses(records, pins, message):
    with pytest.raises(Stop, match=message):
        export(records, pins=pins)
