"""M2-0 spike: a throwaway API to measure the free host before designing M2. Not the real API.

Local:  uvicorn --app-dir spike/m2/api app:app --port 8000
Render: see spike/m2/README.md for the build and start commands.

Every endpoint is a plain `def` (FastAPI runs it in a thread pool), like the real API will be.
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

STARTED = time.time()
SLUG = "pallets/itsdangerous"

app = FastAPI()
# Only the origins listed in ALLOWED_ORIGINS (comma-separated) may call from a browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()],
    allow_methods=["GET"],
)


def memory_mb() -> dict:
    """Current (VmRSS) and peak (VmHWM) resident memory. Linux only; None elsewhere."""
    try:
        with open("/proc/self/status") as f:
            fields = dict(line.split(":", 1) for line in f if ":" in line)
        return {k: int(fields[k].split()[0]) // 1024 for k in ("VmRSS", "VmHWM")}
    except OSError:
        return {"VmRSS": None, "VmHWM": None}


@app.get("/health")
def health():
    return {"ok": True, "uptime_s": round(time.time() - STARTED, 1), "memory_mb": memory_mb()}


@app.get("/slow")
def slow(s: float = 60):
    """Holds the request open for s seconds: does the host's proxy cut it off?"""
    s = min(s, 120)
    time.sleep(s)
    return {"slept_s": s}


@app.get("/db")
def db():
    """Neon connect time (TLS included) and one query, on a fresh connection."""
    from codeask.store import Store, connect

    t0 = time.perf_counter()
    conn = connect()
    t1 = time.perf_counter()
    conn.execute("SELECT 1").fetchone()
    t2 = time.perf_counter()
    chunks = Store(conn).chunk_count(SLUG)
    t3 = time.perf_counter()
    conn.close()
    return {"connect_ms": round((t1 - t0) * 1000), "select1_ms": round((t2 - t1) * 1000),
            "chunk_count_ms": round((t3 - t2) * 1000), "chunks": chunks}


@app.get("/search")
def search(q: str = "How is the signing key derived?"):
    """One real query: Voyage embed + pgvector search. Uses one of the 3 Voyage requests/min."""
    from codeask.embedder import VoyageEmbedder
    from codeask.store import Store, connect

    t0 = time.perf_counter()
    store = Store(connect())
    repo = store.repo(SLUG)
    t1 = time.perf_counter()
    (vector,) = VoyageEmbedder().embed([q[:500]], "query")
    t2 = time.perf_counter()
    rows = store.search(SLUG, repo["settings"]["space"], vector, 5)
    t3 = time.perf_counter()
    store.conn.close()
    return {"connect_ms": round((t1 - t0) * 1000), "embed_ms": round((t2 - t1) * 1000),
            "search_ms": round((t3 - t2) * 1000), "memory_mb": memory_mb(),
            "top": [f"{r['path']}:{r['start_line']}-{r['end_line']} {r['breadcrumb']}" for r in rows]}


@app.get("/ip")
def ip(request: Request):
    """Which headers carry the client IP on this host, and can a client spoof them?"""
    names = ("x-forwarded-for", "true-client-ip", "cf-connecting-ip", "x-real-ip", "forwarded")
    return {"peer": request.client.host if request.client else None,
            **{n: request.headers.get(n) for n in names}}


@app.get("/boom")
def boom():
    """An unhandled error, to check what the host's logs show on a traceback."""
    raise RuntimeError("spike error path")
