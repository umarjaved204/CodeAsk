"""Pre-generation (slice 5, build step 4) offline: fake store, LLM and clock; files in tmp_path.
The rules under test: no re-rolls, at most 2 re-runs of a run with no answer text (Q50), the
token guard and pacing (Q53), and the frozen, pinned questions file (Q48, Q52)."""

import json
from datetime import datetime, timezone

import pytest

from codeask import config
from codeask.askqueue import Pacer
from codeask.llm import GroqError, RateLimited, Reply
from codeask.pregen import Paths, Stop, generate, load_questions

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
