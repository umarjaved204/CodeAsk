"""The CodeAsk API (M2 slice 1: POST /ask only).

Run: uvicorn codeask.api.app:app --port 8000 --workers 1

Endpoints are plain `def`: FastAPI runs them in a thread pool, which the synchronous Voyage
limiter needs. Exactly one worker process, because the limiter is in-process (PLAN.md R10).
Slice 2 adds connection pooling, /status, JSON error handlers and the rest.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from codeask.ask import ask as run_pipeline
from codeask.embedder import VoyageEmbedder
from codeask.llm import GroqClient
from codeask.store import Store, connect

app = FastAPI(title="CodeAsk")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)
# One of each per process: the embedder's limiter must be shared by all requests.
embedder = VoyageEmbedder()
llm = GroqClient()


class AskRequest(BaseModel):
    repo: str = Field(max_length=200, description="owner/name, as ingested")
    question: str = Field(min_length=1, max_length=400)


@app.post("/ask")
def ask(body: AskRequest):
    # A fresh connection per request until slice 2 adds pooling (Render -> Neon: ~20 ms).
    store = Store(connect())
    try:
        repo = store.repo(body.repo.lower())
        if repo is None or repo["settings"]["space"] != embedder.space:
            raise HTTPException(404, "unknown repo")
        (vector,) = embedder.embed([body.question], "query")
        result = run_pipeline(store, llm, repo, body.question, vector)
    finally:
        store.conn.close()
    # Only what the browser needs: no raw answer, usage or rate-limit headers.
    return {key: result[key] for key in ("answer", "citations", "model", "prompt_version")}
