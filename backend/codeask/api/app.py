"""The CodeAsk API (M2 slice 2): featured repos only, no ingestion.

Run: uvicorn codeask.api.app:create_app --factory --port 8000 --workers 1 --no-access-log

Endpoints are plain `def`: FastAPI runs them in a thread pool, which the synchronous Voyage
limiter needs. Exactly one worker process, because the limiter is in-process (PLAN.md R10).
uvicorn's access log is off: it prints the forgeable client address; our own one line per
request has a request id, status, duration and outcome, never question text or IPs (Q16).

Errors (Q22): one middleware registered BEFORE CORS (so it sits inside it) turns every
exception into generic JSON, so the browser can read errors (Starlette's own 500 response is
built outside CORS and reaches the page as "Failed to fetch", M2-0). Never exception text:
psycopg errors name the DB host and user.

Slice 4 (Q42-Q46): every /ask passes the checks in `gate.admit`, waits its turn in the
`AskQueue`, and always gives back its queue place and visitor ticket, counts its tokens and
records its outcome, however it ends. /status answers from memory only (Q40).
"""

from __future__ import annotations

import logging
import math
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import psycopg
import requests
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from codeask import budget, config
from codeask.answer import PROMPT_VERSION
from codeask.api.gate import REFUNDED, Refused, UsageCache, admit
from codeask.ask import ask as run_pipeline
from codeask.ask import public_view
from codeask.askqueue import AskQueue, Pacer
from codeask.deadline import DeadlineExceeded
from codeask.embedder import RateLimited as VoyageRateLimited
from codeask.llm import GroqError
from codeask.llm import RateLimited as GroqRateLimited
from codeask.visitors import UNKNOWN, Visitors, client_key

log = logging.getLogger("uvicorn.error.codeask")


class AskRequest(BaseModel):
    repo: str = Field(max_length=200, description="owner/name, one of GET /repos")
    question: str = Field(min_length=1, max_length=400)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        super().__init__(code)
        self.status, self.code, self.message, self.headers = status, code, message, headers


BUSY = "The service is busy. Please try again in a minute."
# The page words these itself (messages.ts, Q45); these are the API's own short versions.
REFUSALS = {
    "paused": "Live questions are paused right now.",
    "daily_limit": "Live questions are used up for now.",
    "per_ip_limit": "You've reached the daily limit of live questions for one visitor.",
    "in_progress": "Your previous question is still being answered.",
    "busy": BUSY,
}


def refused(r: Refused) -> ApiError:
    headers = None if r.retry_after_s is None else {"Retry-After": str(r.retry_after_s)}
    return ApiError(r.status, r.code, REFUSALS[r.code], headers)


def classify(exc: Exception) -> ApiError:
    """Exception -> the generic error the browser sees (Q22)."""
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, GroqRateLimited):
        return ApiError(503, "busy", BUSY, {"Retry-After": str(int(exc.retry_after + 1))})
    if isinstance(exc, VoyageRateLimited):
        return ApiError(503, "busy", BUSY, {"Retry-After": str(config.VOYAGE_WINDOW_SECONDS)})
    if isinstance(exc, (requests.Timeout, DeadlineExceeded)):
        return ApiError(504, "timeout", "An upstream service timed out. Please try again.")
    if isinstance(exc, (GroqError, requests.RequestException)):
        return ApiError(502, "upstream_error", "An upstream service failed. Please try again.")
    if isinstance(exc, psycopg.Error):
        return ApiError(503, "database_unavailable",
                        "The database is unavailable. Please try again shortly.")
    return ApiError(500, "internal_error", "Something went wrong on the server.")


def error_json(err: ApiError, request: Request) -> JSONResponse:
    request.state.outcome = err.code
    return JSONResponse({"error": err.code, "message": err.message,
                         "request_id": getattr(request.state, "request_id", None)},
                        err.status, headers=err.headers)


def normalize_slug(repo: str) -> str:
    """Case, whitespace, a trailing slash and `.git` don't matter; the result must still be
    exactly one of the featured slugs."""
    return repo.strip().lower().removesuffix("/").removesuffix(".git")


def ip_salt_from_env() -> bytes:
    """IP_SALT (Q46, step 6 decision 4): required, never logged. Rotating it is safe: it only
    resets the in-memory per-visitor counts."""
    from dotenv import load_dotenv

    load_dotenv()
    salt = os.environ.get("IP_SALT", "")
    if len(salt) < config.IP_SALT_MIN_CHARS:
        raise RuntimeError(f"IP_SALT must be set to at least {config.IP_SALT_MIN_CHARS} "
                           "random characters (see .env.example)")
    return salt.encode()


class ModelStatus:
    """Is the configured Groq model available (Q24)? Checked at startup and again after a TTL.
    None = unknown (the check itself failed): /ask stays open, since Groq may be fine."""

    def __init__(self, llm, ttl_s: float = config.MODEL_CHECK_TTL_S, clock=time.monotonic,
                 start=None):
        self.llm, self.ttl_s, self.clock = llm, ttl_s, clock
        self.start = start or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self.available: bool | None = None
        self.checked_at: float | None = None
        self._lock = threading.Lock()
        self._refreshing = False

    def refresh(self) -> bool | None:
        try:
            self.available = self.llm.model in self.llm.available_models()
        except Exception as exc:  # Groq unreachable: don't block /ask on our check
            log.warning("model check failed: %s", type(exc).__name__)
            self.available = None
        self.checked_at = self.clock()
        return self.available

    def _stale(self) -> bool:
        return self.checked_at is None or self.clock() - self.checked_at >= self.ttl_s

    def get(self) -> bool | None:
        """For /ask: re-checks in line when stale."""
        if self._stale():
            self.refresh()
        return self.available

    def peek(self) -> bool | None:
        """For /status, which never waits on Groq (Q40): the last answer, with a stale one
        re-checked in the background, one check at a time."""
        with self._lock:
            refresh = self._stale() and not self._refreshing
            if refresh:
                self._refreshing = True
        if refresh:
            self.start(self._background)
        return self.available

    def _background(self) -> None:
        try:
            self.refresh()
        finally:
            with self._lock:
                self._refreshing = False

    def mark_missing(self) -> None:
        self.available, self.checked_at = False, self.clock()


class TrackedLLM:
    """Notes whether a Groq request was sent: a failure after that may still have spent tokens
    (counted as an estimate), one before it spent none (Q42, Q46)."""

    def __init__(self, llm):
        self.llm, self.started = llm, False

    def chat(self, *args, **kwargs):
        self.started = True
        return self.llm.chat(*args, **kwargs)


def create_app(open_store=None, embedder=None, llm=None, models: ModelStatus | None = None,
               featured: tuple[str, ...] = config.FEATURED_REPOS, ip_salt: bytes | None = None,
               wall=lambda: datetime.now(timezone.utc), queue: AskQueue | None = None,
               visitors: Visitors | None = None) -> FastAPI:
    """Real dependencies by default (uvicorn --factory); tests pass fakes and a salt."""
    if os.environ.get("WEB_CONCURRENCY", "1") != "1":
        raise RuntimeError("CodeAsk needs exactly one worker (in-process limiter): "
                           "set WEB_CONCURRENCY=1")
    salt = ip_salt if ip_salt is not None else ip_salt_from_env()
    if open_store is None:
        from codeask.store import store_session as open_store
    if embedder is None:
        from codeask.embedder import VoyageEmbedder

        embedder = VoyageEmbedder()  # one per process: its limiter is shared by all requests
    if llm is None:
        from codeask.llm import GroqClient

        llm = GroqClient()
    models = models or ModelStatus(llm)
    visitors = visitors or Visitors()
    # The pacer peeks at the embedder's own limiter (fakes have none: no Voyage gate).
    queue = queue or AskQueue(Pacer(getattr(embedder, "limiter", None)))

    def load_usage() -> dict:
        with open_store() as store:
            return store.usage(wall())

    usage = UsageCache(load_usage)

    @asynccontextmanager
    async def lifespan(app):
        log.info("model %s available: %s", llm.model, models.refresh())
        yield

    # No /docs, /redoc or /openapi.json: the public API publishes no schema (slice 6, 3a.2).
    app = FastAPI(title="CodeAsk", lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)

    @app.middleware("http")
    async def errors_and_log(request: Request, call_next):
        request.state.request_id, request.state.outcome = secrets.token_hex(4), None
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            log.warning("request %s failed: %s", request.state.request_id, type(exc).__name__)
            response = error_json(classify(exc), request)
        response.headers["X-Request-Id"] = request.state.request_id
        log.info("request %s %s %s %s %.0f ms %s", request.state.request_id, request.method,
                 request.url.path, response.status_code, (time.perf_counter() - t0) * 1000,
                 request.state.outcome or "-")
        return response

    # Added after the error middleware, so CORS is the outer layer and wraps error JSON too.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",")
                       if o.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        # The headers the page may read. Pinned by tests/test_api.py
        # test_the_browser_may_read_the_request_id_and_retry_after, and mirrored by
        # EXPOSED_HEADERS in frontend/tests/e2e/mocks.ts. Change all three together.
        expose_headers=["X-Request-Id", "Retry-After"],
    )

    @app.exception_handler(StarletteHTTPException)
    def http_error(request: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "error")
        return error_json(ApiError(exc.status_code, code, str(exc.detail)), request)

    @app.exception_handler(RequestValidationError)
    def invalid_request(request: Request, exc: RequestValidationError):
        # Field names only: pydantic's error entries carry the rejected `input` (the question).
        fields = sorted({".".join(str(p) for p in e["loc"][1:]) or "body" for e in exc.errors()})
        return error_json(ApiError(422, "invalid_request",
                                   "Invalid request: " + ", ".join(fields)), request)

    def featured_repo(store, slug: str) -> dict | None:
        repo = store.repo(slug) if slug in featured else None
        return repo if repo and repo["settings"]["space"] == embedder.space else None

    # Render probes HEAD / and GET /; /health is the health check path. Neither touches the
    # DB or the queue, so they answer while those are down.
    @app.api_route("/", methods=["GET", "HEAD"])
    @app.api_route("/health", methods=["GET", "HEAD"])
    def root():
        return {"service": "codeask"}

    @app.get("/status")
    def status(request: Request, response: Response):
        # Per caller (the queue field) and always current: never cached (Q40).
        response.headers["Cache-Control"] = "no-store"
        state = usage.get()
        service = (budget.service(state, queue.count(), wall()) if state is not None
                   else budget.Service("ok"))  # no copy yet: ok, and a refresh has started
        body = {"ok": True, "model": llm.model, "model_available": models.peek(),
                "prompt_version": PROMPT_VERSION, "service": service.status, "queue": None}
        if service.retry_after_s is not None:
            body["retry_after_s"] = service.retry_after_s
        header = request.headers.get("CF-Connecting-IP")
        if header:  # no queue without it (direct onrender.com, local dev): Q40
            place = queue.position(client_key(header, salt), time.monotonic())
            if place:
                body["queue"] = {"position": place[0], "wait_s": place[1]}
        return body

    @app.get("/repos")
    def repos():
        with open_store() as store:
            found = [featured_repo(store, slug) for slug in featured]
        return [{"slug": r["slug"], "url": r["url"], "commit_sha": r["commit_sha"],
                 "ingested_at": r["ingested_at"].isoformat()} for r in found if r]

    def answer(store, body: AskRequest, key: str, deadline: float) -> dict:
        if models.get() is False:
            raise ApiError(503, "model_unavailable", "Live answers are unavailable right now.")
        repo = featured_repo(store, normalize_slug(body.repo))
        if repo is None:
            raise HTTPException(404, "Unknown repo.")
        state = store.usage(wall())  # fails closed: no row, no question (Q44)
        usage.put(state)
        admitted = admit(state, key, visitors, queue, deadline, wall(), time.monotonic())
        if isinstance(admitted, Refused):
            raise refused(admitted)
        visit, place = admitted
        tracked = TrackedLLM(llm)
        result, headers, refund = None, None, True
        try:
            queue.wait_turn(place)
            (vector,) = embedder.embed([body.question], "query", deadline=deadline)
            result = run_pipeline(store, tracked, repo, body.question, vector, deadline)
            refund = False  # answered or ungrounded: a real, shown result
            return result
        except GroqRateLimited as exc:
            headers = exc.headers
            until = budget.daily_block_until(exc.retry_after, wall())
            if until is None:
                raise
            # Groq's own daily limit (Q46): no question can succeed until then.
            log.warning("Groq daily limit reached; blocked for %.0f s", exc.retry_after)
            try:
                store.set_usage(blocked_until=until)
            except Exception as db_exc:  # the visitor still gets the honest answer
                log.warning("blocked_until not saved: %s", type(db_exc).__name__)
            raise ApiError(429, "daily_limit", REFUSALS["daily_limit"],
                           {"Retry-After": str(math.ceil(exc.retry_after))}) from exc
        except GroqError as exc:
            if exc.status != 404:
                raise
            models.mark_missing()  # Groq says the model is gone (R13)
            raise ApiError(503, "model_unavailable",
                           "Live answers are unavailable right now.") from exc
        except Exception as exc:
            refund = classify(exc).code in REFUNDED
            raise
        finally:
            used = result["usage"] if result else None
            queue.leave(place, time.monotonic(), (used or {}).get("completion_tokens"),
                        result["headers"] if result else headers, tracked.started)
            visitors.finish(visit, refund=refund)
            tokens = budget.tokens_used(used, tracked.started)
            if tokens:
                try:
                    store.add_tokens(wall(), tokens)
                except Exception as exc:  # the answer still goes out; the gap is logged
                    log.warning("token count not saved (%d tokens): %s", tokens,
                                type(exc).__name__)

    def count(store, outcome: str, key: str) -> None:
        """Daily aggregates only (Q16): never question text or IPs."""
        try:
            day = wall().date()
            store.count_outcome(day, outcome)
            if key == UNKNOWN:
                store.count_outcome(day, "no_client_ip")
        except Exception as exc:
            log.warning("outcome not counted: %s", type(exc).__name__)

    @app.post("/ask")
    def ask(body: AskRequest, request: Request):
        deadline = time.monotonic() + config.ASK_DEADLINE_S  # from entry (Q43, Q46)
        key = client_key(request.headers.get("CF-Connecting-IP"), salt)
        with open_store() as store:
            outcome = "internal_error"
            try:
                result = answer(store, body, key, deadline)
                outcome = "answered" if result["grounded"] else "ungrounded"
            except HTTPException as exc:
                outcome = {404: "not_found"}.get(exc.status_code, "error")
                raise
            except Exception as exc:
                outcome = classify(exc).code
                raise
            finally:
                count(store, outcome, key)
        request.state.outcome = outcome
        return public_view(result)

    return app
