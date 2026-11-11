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
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from contextlib import asynccontextmanager

import psycopg
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from codeask import config
from codeask.answer import PROMPT_VERSION
from codeask.ask import ask as run_pipeline
from codeask.ask import public_view
from codeask.embedder import RateLimited as VoyageRateLimited
from codeask.llm import GroqError
from codeask.llm import RateLimited as GroqRateLimited

log = logging.getLogger("uvicorn.error.codeask")  # uvicorn's handler prints it


class AskRequest(BaseModel):
    repo: str = Field(max_length=200, description="owner/name, one of GET /repos")
    question: str = Field(min_length=1, max_length=400)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        super().__init__(code)
        self.status, self.code, self.message, self.headers = status, code, message, headers


BUSY = "The service is busy. Please try again in a minute."


def classify(exc: Exception) -> ApiError:
    """Exception -> the generic error the browser sees (Q22)."""
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, GroqRateLimited):
        return ApiError(503, "busy", BUSY, {"Retry-After": str(int(exc.retry_after + 1))})
    if isinstance(exc, VoyageRateLimited):
        return ApiError(503, "busy", BUSY, {"Retry-After": str(config.VOYAGE_WINDOW_SECONDS)})
    if isinstance(exc, requests.Timeout):
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


class ModelStatus:
    """Is the configured Groq model available (Q24)? Checked at startup and again after a TTL.
    None = unknown (the check itself failed): /ask stays open, since Groq may be fine."""

    def __init__(self, llm, ttl_s: float = config.MODEL_CHECK_TTL_S, clock=time.monotonic):
        self.llm, self.ttl_s, self.clock = llm, ttl_s, clock
        self.available: bool | None = None
        self.checked_at: float | None = None

    def refresh(self) -> bool | None:
        try:
            self.available = self.llm.model in self.llm.available_models()
        except Exception as exc:  # Groq unreachable: don't block /ask on our check
            log.warning("model check failed: %s", type(exc).__name__)
            self.available = None
        self.checked_at = self.clock()
        return self.available

    def get(self) -> bool | None:
        if self.checked_at is None or self.clock() - self.checked_at >= self.ttl_s:
            self.refresh()
        return self.available

    def mark_missing(self) -> None:
        self.available, self.checked_at = False, self.clock()


def create_app(open_store=None, embedder=None, llm=None, models: ModelStatus | None = None,
               featured: tuple[str, ...] = config.FEATURED_REPOS) -> FastAPI:
    """Real dependencies by default (uvicorn --factory); tests pass fakes."""
    if os.environ.get("WEB_CONCURRENCY", "1") != "1":
        raise RuntimeError("CodeAsk needs exactly one worker (in-process limiter): "
                           "set WEB_CONCURRENCY=1")
    if open_store is None:
        from codeask.store import store_session as open_store
    if embedder is None:
        from codeask.embedder import VoyageEmbedder

        embedder = VoyageEmbedder()  # one per process: its limiter is shared by all requests
    if llm is None:
        from codeask.llm import GroqClient

        llm = GroqClient()
    models = models or ModelStatus(llm)

    @asynccontextmanager
    async def lifespan(app):
        log.info("model %s available: %s", llm.model, models.refresh())
        yield

    app = FastAPI(title="CodeAsk", lifespan=lifespan)

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

    @app.api_route("/", methods=["GET", "HEAD"])  # Render probes HEAD / and GET /
    def root():
        return {"service": "codeask"}

    @app.get("/status")
    def status():
        return {"ok": True, "model": llm.model, "model_available": models.get(),
                "prompt_version": PROMPT_VERSION}

    @app.get("/repos")
    def repos():
        with open_store() as store:
            found = [featured_repo(store, slug) for slug in featured]
        return [{"slug": r["slug"], "url": r["url"], "commit_sha": r["commit_sha"],
                 "ingested_at": r["ingested_at"].isoformat()} for r in found if r]

    @app.post("/ask")
    def ask(body: AskRequest, request: Request):
        if models.get() is False:
            raise ApiError(503, "model_unavailable", "Live answers are unavailable right now.")
        with open_store() as store:
            repo = featured_repo(store, normalize_slug(body.repo))
            if repo is None:
                raise HTTPException(404, "Unknown repo.")
            (vector,) = embedder.embed([body.question], "query")
            try:
                result = run_pipeline(store, llm, repo, body.question, vector)
            except GroqError as exc:
                if exc.status != 404:
                    raise
                models.mark_missing()  # Groq says the model is gone (R13)
                raise ApiError(503, "model_unavailable",
                               "Live answers are unavailable right now.") from exc
        request.state.outcome = "answered" if result["grounded"] else "ungrounded"
        return public_view(result)

    return app
