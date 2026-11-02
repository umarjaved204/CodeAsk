"""The API with fakes (no network): errors inside CORS, featured-only, grounding, model check,
logs (PLAN.md slice 2, Q22-Q24, Q16)."""

import logging
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
import pytest
import requests
from fastapi.testclient import TestClient

from codeask.api.app import ModelStatus, create_app
from codeask.embedder import RateLimited as VoyageRateLimited
from codeask.llm import GroqError, RateLimited, Reply

ORIGIN = "http://localhost:3000"
SLUG, SPACE, MODEL = "pallets/itsdangerous", "voyage:1024:document", "qwen/test"
QUESTION = "How is the signing key derived? UNIQUE-QUESTION-TEXT"
REPO = {"slug": SLUG, "url": f"https://github.com/{SLUG}", "commit_sha": "abc",
        "settings": {"space": SPACE}, "ingested_at": datetime(2026, 11, 3, tzinfo=timezone.utc)}
ROW = {"path": "signer.py", "start_line": 1, "end_line": 5, "token_count": 10,
       "kind": "function", "breadcrumb": "f", "distance": 0.4,
       "content": "\n".join(f"line {i}" for i in range(1, 6))}


class FakeStore:
    repos = {SLUG: REPO, "other/repo": {**REPO, "slug": "other/repo"}}  # other: not featured

    def repo(self, slug):
        return self.repos.get(slug)

    def search(self, slug, space, vector, k):
        return [ROW]

    def file_chunks(self, slug, paths):
        return [ROW]


class FakeEmbedder:
    space = SPACE

    def __init__(self, error=None):
        self.error, self.calls = error, 0

    def embed(self, texts, input_type):
        self.calls += 1
        if self.error:
            raise self.error
        return [[0.0]]


class FakeLLM:
    model = MODEL

    def __init__(self, text="Derived here [signer.py:2-3].", error=None, models=(MODEL,)):
        self.text, self.error, self.models = text, error, models

    def chat(self, messages):
        if self.error:
            raise self.error
        return Reply(self.text, None, {}, {}, MODEL, 0.1, 0)

    def available_models(self):
        if isinstance(self.models, Exception):
            raise self.models
        return set(self.models)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@contextmanager
def fake_session():
    yield FakeStore()


def client(monkeypatch, embedder=None, llm=None, models=None):
    monkeypatch.setenv("ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    llm = llm or FakeLLM()
    app = create_app(fake_session, embedder or FakeEmbedder(), llm, models,
                     featured=(SLUG, "psf/requests"))
    return TestClient(app, headers={"Origin": ORIGIN})


def ask(c, repo=SLUG, question=QUESTION):
    return c.post("/ask", json={"repo": repo, "question": question})


# ---------- errors reach the browser as JSON with CORS headers (Q22) ----------
def test_unhandled_error_is_generic_json_with_cors_and_a_request_id(monkeypatch):
    secret = ValueError("connection to host db.internal user=admin failed")
    with client(monkeypatch, embedder=FakeEmbedder(secret)) as c:
        r = ask(c)
    assert r.status_code == 500
    assert r.headers["access-control-allow-origin"] == ORIGIN
    body = r.json()
    assert body["error"] == "internal_error" and "db.internal" not in r.text
    assert body["request_id"] == r.headers["x-request-id"]


@pytest.mark.parametrize("embedder, llm, status, code, retry_after", [
    (None, FakeLLM(error=RateLimited("429", 12.5)), 503, "busy", "13"),
    (FakeEmbedder(VoyageRateLimited("429")), None, 503, "busy", "65"),
    (FakeEmbedder(requests.Timeout("t")), None, 504, "timeout", None),
    (None, FakeLLM(error=GroqError("Groq 500: boom", 500)), 502, "upstream_error", None),
    (FakeEmbedder(psycopg.OperationalError("host=x")), None, 503, "database_unavailable", None),
])
def test_upstream_failures_map_to_generic_errors(monkeypatch, embedder, llm, status, code,
                                                 retry_after):
    with client(monkeypatch, embedder=embedder, llm=llm) as c:
        r = ask(c)
    assert (r.status_code, r.json()["error"]) == (status, code)
    assert r.headers.get("retry-after") == retry_after
    assert r.headers["access-control-allow-origin"] == ORIGIN


def test_too_long_question_is_422_without_echoing_or_logging_it(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    with client(monkeypatch) as c:
        r = ask(c, question=QUESTION + "x" * 400)
    assert r.status_code == 422 and r.json()["message"] == "Invalid request: question"
    assert "UNIQUE-QUESTION-TEXT" not in r.text
    assert "UNIQUE-QUESTION-TEXT" not in caplog.text


def test_unknown_route_is_json_404(monkeypatch):
    with client(monkeypatch) as c:
        r = c.get("/nope")
    assert r.status_code == 404 and r.json()["error"] == "not_found"


# ---------- routes ----------
def test_head_and_get_root_answer(monkeypatch):
    with client(monkeypatch) as c:
        assert c.head("/").status_code == 200
        assert c.get("/").json() == {"service": "codeask"}


def test_repos_lists_only_featured_repos_that_are_ingested(monkeypatch):
    with client(monkeypatch) as c:  # featured: itsdangerous (ingested), requests (not)
        repos = c.get("/repos").json()
    assert [r["slug"] for r in repos] == [SLUG]
    assert repos[0]["ingested_at"] == "2026-11-03T00:00:00+00:00"


@pytest.mark.parametrize("repo", ["PALLETS/ItsDangerous", " pallets/itsdangerous ",
                                  "pallets/itsdangerous.git", "pallets/itsdangerous/"])
def test_slug_variants_of_a_featured_repo_are_accepted(monkeypatch, repo):
    with client(monkeypatch) as c:
        assert ask(c, repo=repo).status_code == 200


@pytest.mark.parametrize("repo", ["other/repo", "Other/Repo.git/", "psf/requests",
                                  "pallets/itsdangerous/../../other/repo", "pallets/x"])
def test_non_featured_or_not_ingested_repos_are_404_before_any_embedding(monkeypatch, repo):
    embedder = FakeEmbedder()
    with client(monkeypatch, embedder=embedder) as c:
        r = ask(c, repo=repo)
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    assert embedder.calls == 0


# ---------- grounding (Q23) ----------
def test_grounded_answer_is_shown(monkeypatch):
    with client(monkeypatch) as c:
        body = ask(c).json()
    assert body["grounded"] and body["answer"] == "Derived here [1](cite:1)."


def test_ungrounded_answer_text_is_withheld(monkeypatch):
    with client(monkeypatch, llm=FakeLLM("Probably HMAC.")) as c:
        body = ask(c).json()
    assert body["grounded"] is False and body["answer"] is None
    assert body["possibly_relevant"][0]["path"] == "signer.py"


# ---------- model check (Q24) ----------
def test_missing_model_degrades_ask_and_status(monkeypatch):
    with client(monkeypatch, llm=FakeLLM(models=("other",))) as c:
        assert c.get("/status").json()["model_available"] is False
        r = ask(c)
    assert r.status_code == 503 and r.json()["error"] == "model_unavailable"


def test_failed_model_check_is_unknown_and_ask_stays_open(monkeypatch):
    with client(monkeypatch, llm=FakeLLM(models=requests.ConnectionError())) as c:
        assert c.get("/status").json()["model_available"] is None
        assert ask(c).status_code == 200


def test_groq_404_marks_the_model_missing(monkeypatch):
    llm = FakeLLM(error=GroqError("Groq 404: model_not_found", 404))
    with client(monkeypatch, llm=llm) as c:
        assert ask(c).json()["error"] == "model_unavailable"
        assert c.get("/status").json()["model_available"] is False


def test_model_list_is_rechecked_after_the_ttl():
    clock, llm = Clock(), FakeLLM(models=())
    status = ModelStatus(llm, ttl_s=600, clock=clock)
    assert status.get() is False
    llm.models = (MODEL,)
    clock.t = 599
    assert status.get() is False  # cached
    clock.t = 600
    assert status.get() is True


# ---------- startup and logs ----------
def test_more_than_one_worker_refuses_to_start(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(RuntimeError, match="exactly one worker"):
        create_app(fake_session, FakeEmbedder(), FakeLLM())


def test_one_log_line_per_request_with_id_and_outcome_but_no_question_or_ip(monkeypatch,
                                                                         caplog):
    caplog.set_level(logging.INFO)
    with client(monkeypatch) as c:
        r = ask(c)
    lines = [m for m in caplog.messages if m.startswith("request ")]
    assert len(lines) == 1
    assert r.headers["x-request-id"] in lines[0] and "POST /ask 200" in lines[0]
    assert lines[0].endswith("answered")
    assert "UNIQUE-QUESTION-TEXT" not in caplog.text and "testclient" not in caplog.text
