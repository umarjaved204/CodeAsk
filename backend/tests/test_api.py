"""The API with fakes (no network): errors inside CORS, featured-only, grounding, model check,
logs (PLAN.md slice 2, Q22-Q24, Q16)."""

import json
import logging
import os
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
import requests
from fastapi.testclient import TestClient

from codeask import config
from codeask.api.app import (COLD_START_DEFAULTS, ModelStatus, cold_start_from_env,
                             create_app)
from codeask.askqueue import AskQueue, Pacer
from codeask.deadline import DeadlineExceeded
from codeask.embedder import RateLimited as VoyageRateLimited
from codeask.llm import GroqError, RateLimited, Reply
from codeask.visitors import Visitors, client_key

SALT = b"test-salt-0123456789"
IP, OTHER_IP = "203.0.113.7", "203.0.113.8"
NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
USAGE = {"prompt_tokens": 2_700, "completion_tokens": 300, "total_tokens": 3_000}
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

    def __init__(self, **settings):
        self.settings = {"public_budget_tokens": 120_000, "per_ip_daily": 5, "paused": False,
                         "blocked_until": None, **settings}
        self.tokens, self.outcomes = [], Counter()
        self.usage_error = self.search_error = None

    def repo(self, slug):
        return self.repos.get(slug)

    def usage(self, now):
        if self.usage_error:
            raise self.usage_error
        return {**self.settings, "buckets": [(now, sum(self.tokens))] if self.tokens else []}

    def add_tokens(self, now, tokens):
        self.tokens.append(tokens)

    def count_outcome(self, day, outcome):
        self.outcomes[outcome] += 1

    def set_usage(self, **changes):
        self.settings.update(changes)

    def search(self, slug, space, vector, k):
        if self.search_error:
            raise self.search_error
        return [ROW]

    def file_chunks(self, slug, paths):
        return [ROW]


class FakeEmbedder:
    space = SPACE

    def __init__(self, error=None):
        self.error, self.calls, self.deadline = error, 0, None

    def embed(self, texts, input_type, deadline=None):
        self.calls += 1
        self.deadline = deadline
        if self.error:
            raise self.error
        return [[0.0]]


class FakeLLM:
    model = MODEL

    def __init__(self, text="Derived here [signer.py:2-3].", error=None, models=(MODEL,)):
        self.text, self.error, self.models = text, error, models
        self.deadline = None

    def chat(self, messages, deadline=None):
        self.deadline = deadline
        if self.error:
            raise self.error
        return Reply(self.text, None, USAGE, {}, MODEL, 0.1, 0)

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


class OpenPacer(Pacer):
    """Never paces: the API tests ask several questions within a minute. The real pacing is
    tested in test_askqueue.py and test_gate.py."""

    def next_start(self, now):
        return now


def client(monkeypatch, embedder=None, llm=None, models=None, store=None, queue=None,
           visitors=None):
    monkeypatch.setenv("ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    llm = llm or FakeLLM()
    store = store or FakeStore()

    @contextmanager
    def session():
        yield store

    app = create_app(session, embedder or FakeEmbedder(), llm, models,
                     featured=(SLUG, "psf/requests"), ip_salt=SALT, wall=lambda: NOW,
                     queue=queue or AskQueue(OpenPacer()), visitors=visitors)
    return TestClient(app, headers={"Origin": ORIGIN})


def ask(c, repo=SLUG, question=QUESTION, ip=None):
    headers = {"CF-Connecting-IP": ip} if ip else {}
    return c.post("/ask", json={"repo": repo, "question": question}, headers=headers)


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
    (FakeEmbedder(DeadlineExceeded()), None, 504, "timeout", None),
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


def test_the_browser_may_read_the_request_id_and_retry_after(monkeypatch):
    # A cross-origin page can read a response header only if it is exposed. This pins the
    # backend's list (app.py create_app). The browser tests copy it as EXPOSED_HEADERS in
    # frontend/tests/e2e/mocks.ts and show what the page does without it (Q38). Change all
    # three together.
    with client(monkeypatch, llm=FakeLLM(error=RateLimited("429", 12.5))) as c:
        r = ask(c)
    assert r.status_code == 503 and "retry-after" in r.headers and "x-request-id" in r.headers
    exposed = {h.strip().lower() for h in r.headers["access-control-expose-headers"].split(",")}
    assert {"x-request-id", "retry-after"} <= exposed


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


class BrokenStore:
    """Every store call fails, as when the database is down."""

    def __getattr__(self, name):
        raise psycopg.OperationalError("database is down")


@pytest.mark.parametrize("path", ["/", "/health"])
def test_root_and_health_answer_while_the_database_is_down(monkeypatch, path):
    with client(monkeypatch, store=BrokenStore()) as c:
        assert c.head(path).status_code == 200
        r = c.get(path)
    assert r.status_code == 200 and r.json() == {"service": "codeask"}


def test_the_route_inventory_is_exactly_the_public_api(monkeypatch):
    # Anything new here must be public on purpose: ingestion, cloning and gc never are.
    with client(monkeypatch) as c:
        paths = {route.path for route in c.app.routes}
        assert paths == {"/", "/health", "/status", "/repos", "/ask"}
        for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            assert c.get(path).status_code == 404, path


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


# ---------- one deadline per question (Q43) ----------
def test_ask_passes_one_deadline_from_entry_to_voyage_and_groq(monkeypatch):
    embedder, llm = FakeEmbedder(), FakeLLM()
    before = time.monotonic()
    with client(monkeypatch, embedder=embedder, llm=llm) as c:
        ask(c)
    assert embedder.deadline == llm.deadline
    after = time.monotonic()
    assert before + config.ASK_DEADLINE_S <= embedder.deadline <= after + config.ASK_DEADLINE_S


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


@pytest.mark.parametrize("value", ["", "tooshort-secret"])
def test_a_missing_or_short_ip_salt_refuses_to_start_without_printing_it(monkeypatch, value):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.setenv("IP_SALT", value)  # set (even empty), so .env can't override it
    with pytest.raises(RuntimeError, match="IP_SALT") as err:
        create_app(fake_session, FakeEmbedder(), FakeLLM())
    assert not value or value not in str(err.value)


# ---------- the cold-start constants from the environment (slice 6, 3a.5) ----------
SEED, FLOOR = "PROJECTED_SERVICE_SEED_S", "MIN_TIME_TO_START_S"


@pytest.mark.parametrize("environ, expected", [
    ({}, COLD_START_DEFAULTS),  # unset: the code's values
    ({SEED: " ", FLOOR: ""}, COLD_START_DEFAULTS),  # empty counts as unset
    ({SEED: "20", FLOOR: "30"}, {SEED: 20, FLOOR: 30}),
    ({SEED: "30", FLOOR: "30"}, {SEED: 30, FLOOR: 30}),  # both bounds are inclusive
    ({SEED: "1"}, {SEED: 1, FLOOR: COLD_START_DEFAULTS[FLOOR]}),
])
def test_cold_start_constants_accepted(environ, expected):
    assert cold_start_from_env(environ) == expected


@pytest.mark.parametrize("environ, message", [
    ({SEED: "0"}, "need 0 <"),
    ({SEED: "-5"}, "need 0 <"),
    ({SEED: "20", FLOOR: "10"}, "need 0 <"),  # the seed above the floor
    ({FLOOR: "31"}, r"\(30\)"),  # above 90 - 60
    ({SEED: "fast"}, "whole number"),
    ({FLOOR: "12.5"}, "whole number"),
])
def test_cold_start_constants_refused(environ, message):
    with pytest.raises(RuntimeError, match=message):
        cold_start_from_env(environ)


def test_the_app_uses_and_logs_the_constants_from_the_environment(monkeypatch, caplog):
    for name in (SEED, FLOOR):  # create_app sets them on config: restored after this test
        monkeypatch.setattr(config, name, getattr(config, name))
    monkeypatch.setenv(SEED, "20")
    monkeypatch.setenv(FLOOR, "30")
    caplog.set_level(logging.INFO)
    with client(monkeypatch):
        pass
    assert (config.PROJECTED_SERVICE_SEED_S, config.MIN_TIME_TO_START_S) == (20, 30)
    assert (f"cold-start constants: {SEED}=20 (env), {FLOOR}=30 (env)") in caplog.messages


def test_a_constant_out_of_bounds_stops_startup(monkeypatch):
    monkeypatch.setenv(FLOOR, "31")
    with pytest.raises(RuntimeError, match="MIN_TIME_TO_START_S"):
        client(monkeypatch)


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


def test_neither_the_ip_its_hash_nor_the_salt_is_ever_logged(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    with client(monkeypatch) as c:
        ask(c, ip=IP)
        c.get("/status", headers={"CF-Connecting-IP": IP})
    for secret in (IP, client_key(IP, SALT), SALT.decode()):
        assert secret not in caplog.text


# ---------- refusals (Q44-Q46, step 6): each code, status and Retry-After ----------
def test_paused_is_a_503_without_retry_after_and_nothing_runs(monkeypatch):
    store, embedder = FakeStore(paused=True), FakeEmbedder()
    with client(monkeypatch, embedder=embedder, store=store) as c:
        r = ask(c)
    assert (r.status_code, r.json()["error"]) == (503, "paused")
    assert "retry-after" not in r.headers
    assert embedder.calls == 0 and store.tokens == []
    assert store.outcomes["paused"] == 1


def test_a_spent_budget_is_daily_limit_429_with_whole_seconds(monkeypatch):
    store = FakeStore(public_budget_tokens=config.QUESTION_RESERVE_TOKENS - 1)
    with client(monkeypatch, store=store) as c:
        r = ask(c)
    assert (r.status_code, r.json()["error"]) == (429, "daily_limit")
    assert r.headers["retry-after"].isdigit() and int(r.headers["retry-after"]) > 0


def test_a_daily_block_is_daily_limit_until_it_ends(monkeypatch):
    store = FakeStore(blocked_until=NOW + timedelta(hours=1))
    with client(monkeypatch, store=store) as c:
        r = ask(c)
    assert (r.status_code, r.headers["retry-after"]) == (429, "3600")


def test_per_ip_limit_is_per_visitor(monkeypatch):
    with client(monkeypatch, store=FakeStore(per_ip_daily=1)) as c:
        assert ask(c, ip=IP).status_code == 200
        r = ask(c, ip=IP)
        assert (r.status_code, r.json()["error"]) == (429, "per_ip_limit")
        assert r.headers["retry-after"].isdigit()
        assert ask(c, ip=OTHER_IP).status_code == 200


def test_a_question_still_in_flight_is_in_progress_until_its_deadline(monkeypatch):
    visitors = Visitors()
    visitors.accept(client_key(IP, SALT), 5, time.monotonic() + 30)
    with client(monkeypatch, visitors=visitors) as c:
        r = ask(c, ip=IP)
    assert (r.status_code, r.json()["error"]) == (429, "in_progress")
    assert 29 <= int(r.headers["retry-after"]) <= 30


def test_a_busy_queue_is_503_busy_and_the_visitor_is_not_charged(monkeypatch):
    queue, visitors = AskQueue(Pacer()), Visitors()  # the real pacer, one question running
    now = time.monotonic()
    queue.try_start(queue.join("someone", now + 90, now), now)
    with client(monkeypatch, queue=queue, visitors=visitors) as c:
        r = ask(c, ip=IP)
    assert (r.status_code, r.json()["error"]) == (503, "busy")
    assert int(r.headers["retry-after"]) >= 1
    assert visitors.check(client_key(IP, SALT), 1) is None


def test_no_usage_row_fails_closed_before_any_work(monkeypatch):
    store, embedder = FakeStore(), FakeEmbedder()
    store.usage_error = psycopg.OperationalError("host=db.secret")
    with client(monkeypatch, embedder=embedder, store=store) as c:
        r = ask(c)
    assert (r.status_code, r.json()["error"]) == (503, "database_unavailable")
    assert embedder.calls == 0 and "db.secret" not in r.text


# ---------- refunds and token counting ----------
REFUND_CASES = [  # (embedder, llm, search error) -> the code the visitor sees
    (FakeEmbedder(DeadlineExceeded()), None, None, "timeout"),
    (FakeEmbedder(VoyageRateLimited("429")), None, None, "busy"),
    (FakeEmbedder(requests.ConnectionError("x")), None, None, "upstream_error"),
    (None, FakeLLM(error=GroqError("Groq 500: boom", 500)), None, "upstream_error"),
    (None, FakeLLM(error=GroqError("Groq 404", 404)), None, "model_unavailable"),
    (None, FakeLLM(error=RateLimited("429", 12.5)), None, "busy"),
    (None, FakeLLM(error=RateLimited("429", 3600)), None, "daily_limit"),
    (None, None, psycopg.OperationalError("x"), "database_unavailable"),
    (None, FakeLLM(error=ValueError("bug")), None, "internal_error"),
]


@pytest.mark.parametrize("embedder, llm, search_error, code", REFUND_CASES)
def test_a_failure_on_our_side_after_acceptance_is_refunded(monkeypatch, embedder, llm,
                                                            search_error, code):
    store, visitors = FakeStore(per_ip_daily=1), Visitors()
    store.search_error = search_error
    with client(monkeypatch, embedder=embedder, llm=llm, store=store, visitors=visitors) as c:
        r = ask(c, ip=IP)
    assert r.json()["error"] == code
    assert visitors.check(client_key(IP, SALT), 1) is None  # the question was given back
    assert store.outcomes[code] == 1


@pytest.mark.parametrize("text, outcome", [("Derived here [signer.py:2-3].", "answered"),
                                           ("Probably HMAC.", "ungrounded")])
def test_a_shown_result_is_not_refunded_and_counts_its_real_tokens(monkeypatch, text, outcome):
    store, visitors = FakeStore(per_ip_daily=1), Visitors()
    with client(monkeypatch, llm=FakeLLM(text), store=store, visitors=visitors) as c:
        assert ask(c, ip=IP).status_code == 200
    assert visitors.check(client_key(IP, SALT), 1).code == "per_ip_limit"
    assert store.tokens == [3_000]
    assert store.outcomes[outcome] == 1


def test_tokens_are_estimated_only_once_groq_was_called(monkeypatch):
    after = FakeStore()
    with client(monkeypatch, llm=FakeLLM(error=GroqError("Groq 500", 500)), store=after) as c:
        ask(c)
    assert after.tokens == [config.UNKNOWN_OUTCOME_TOKENS]
    before = FakeStore()
    with client(monkeypatch, embedder=FakeEmbedder(VoyageRateLimited("429")), store=before) as c:
        ask(c)
    assert before.tokens == []


def test_a_long_groq_429_blocks_the_day_and_a_short_one_is_busy(monkeypatch):
    store = FakeStore()
    with client(monkeypatch, llm=FakeLLM(error=RateLimited("429", 3600)), store=store) as c:
        r = ask(c)
    assert (r.status_code, r.headers["retry-after"]) == (429, "3600")
    assert store.settings["blocked_until"] == NOW + timedelta(seconds=3600)
    short = FakeStore()
    with client(monkeypatch, llm=FakeLLM(error=RateLimited("429", 12.5)), store=short) as c:
        assert ask(c).status_code == 503
    assert short.settings["blocked_until"] is None


def test_outcomes_count_the_unknown_bucket_but_never_more(monkeypatch):
    store = FakeStore()
    with client(monkeypatch, store=store) as c:
        ask(c)  # no CF-Connecting-IP: the shared bucket
        ask(c, ip=IP)
        ask(c, repo="other/repo", ip=OTHER_IP)
    assert store.outcomes == Counter({"answered": 2, "no_client_ip": 1, "not_found": 1})


# ---------- /status from memory (Q40, Q45, Q46 C4) ----------
def test_status_is_never_cached_and_has_no_queue_without_a_client_ip(monkeypatch):
    with client(monkeypatch) as c:
        r = c.get("/status")
    assert r.headers["cache-control"] == "no-store"
    assert r.json()["service"] == "ok" and r.json()["queue"] is None


@pytest.mark.parametrize("settings, service, retry", [
    ({"paused": True}, "paused", None),
    ({"public_budget_tokens": 0}, "daily_limit", 86_400),
])
def test_status_service_follows_the_last_usage_read(monkeypatch, settings, service, retry):
    with client(monkeypatch, store=FakeStore(**settings)) as c:
        ask(c)  # every /ask reads the row and refreshes the copy
        body = c.get("/status").json()
    assert body["service"] == service and body.get("retry_after_s") == retry


def test_status_without_the_database_still_answers_ok(monkeypatch):
    store = FakeStore()
    store.usage_error = psycopg.OperationalError("host=db.secret")
    with client(monkeypatch, store=store) as c:
        r = c.get("/status")
    assert r.status_code == 200 and r.json()["service"] == "ok"


def test_status_gives_the_callers_own_place(monkeypatch):
    queue, now = AskQueue(OpenPacer()), time.monotonic()
    queue.try_start(queue.join("someone", now + 90, now), now)
    queue.join(client_key(IP, SALT), now + 90, now)
    with client(monkeypatch, queue=queue) as c:
        mine = c.get("/status", headers={"CF-Connecting-IP": IP}).json()["queue"]
        other = c.get("/status", headers={"CF-Connecting-IP": OTHER_IP}).json()["queue"]
        nobody = c.get("/status").json()["queue"]
    assert mine == {"position": 2, "wait_s": 0} and other is None and nobody is None


# ---------- the frontend contract (step 8): real replies, not hand-written mocks ----------
CONTRACT = Path(__file__).resolve().parents[2] / "frontend" / "tests" / "contract" / "backend-replies.json"
CONTRACT_HEADERS = ("retry-after", "access-control-expose-headers", "cache-control")


def contract_replies(monkeypatch) -> dict:
    """Each refusal the page handles and each /status shape, as the real app sends them."""
    replies = {}

    def record(name, r):
        body = r.json()
        if isinstance(body, dict) and "request_id" in body:
            body["request_id"] = "a1b2c3d4"  # random per request; the page only shows it
        replies[name] = {"status": r.status_code, "body": body,
                         "headers": {h: r.headers[h] for h in CONTRACT_HEADERS if h in r.headers}}

    key = client_key(IP, SALT)

    def in_flight():
        visitors = Visitors(clock=lambda: 1_000.0)
        visitors.accept(key, 5, 1_030.0)  # a question in flight with 30 s left
        return {"visitors": visitors}

    def line(pacer, mine=False):
        queue, now = AskQueue(pacer), time.monotonic()
        queue.try_start(queue.join("someone", now + 90, now), now)
        if mine:
            queue.join(key, now + 90, now)
        return {"queue": queue}

    cases = [  # built just before each request, so time-based values don't drift
        ("ask paused", lambda: {"store": FakeStore(paused=True)}, "ask"),
        ("ask daily_limit", lambda: {"store": FakeStore(public_budget_tokens=0)}, "ask"),
        ("ask per_ip_limit", lambda: {"store": FakeStore(per_ip_daily=0)}, "ask"),
        ("ask in_progress", in_flight, "ask"),
        ("ask busy", lambda: line(Pacer()), "ask"),  # projected 78 s: busy, Retry-After 19
        ("status ok", dict, "status"),
        ("status paused", lambda: {"store": FakeStore(paused=True)}, "ask+status"),
        ("status daily_limit", lambda: {"store": FakeStore(public_budget_tokens=0)}, "ask+status"),
        ("status queue", lambda: line(OpenPacer(), mine=True), "status"),
    ]
    for name, deps, calls in cases:
        with client(monkeypatch, **deps()) as c:
            if "ask" in calls:
                r = ask(c, ip=IP)
            if "status" in calls:
                r = c.get("/status", headers={"CF-Connecting-IP": IP})
            record(name, r)
    return replies


def test_the_frontend_contract_file_is_current(monkeypatch):
    text = json.dumps(contract_replies(monkeypatch), indent=2, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_CONTRACT") == "1":
        CONTRACT.parent.mkdir(parents=True, exist_ok=True)
        CONTRACT.write_text(text, encoding="utf-8")
    assert CONTRACT.exists() and CONTRACT.read_text(encoding="utf-8") == text, (
        "the backend's replies changed: rerun this test with UPDATE_CONTRACT=1 and commit "
        "frontend/tests/contract/backend-replies.json (the frontend logic tests read it)")


def test_status_never_waits_on_the_model_check():
    clock, llm, started = Clock(), FakeLLM(models=()), []
    status = ModelStatus(llm, ttl_s=600, clock=clock, start=started.append)
    assert status.peek() is None  # no answer yet, and a check started in the background
    assert status.peek() is None and len(started) == 1  # one at a time
    started.pop()()
    assert status.peek() is False and not started
