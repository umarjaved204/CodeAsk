"""Voyage embeddings behind a shared rate limiter.

The no-card limit is 3 requests per minute for everything on this key. M0 showed two things
the limiter has to respect: Voyage seems to count a request from when it arrives or completes,
not from when we sent it (so we stamp at completion and add a 5 s margin), and it sends no
Retry-After header (so a 429 waits one full window).
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Callable

from codeask import config


class Limiter:
    """Sliding window: at most `per_window` requests in flight or completed within the last
    `window_s` seconds. A request holds a slot from acquire() until release(), and the slot
    frees `window_s` after completion.

    `reserved_for_queries` slots are off-limits to ingestion, so a visitor's question never
    waits behind a whole repo (M2). In-process only: it can't see another process using the key.
    """

    def __init__(self, per_window: int = config.VOYAGE_REQUESTS_PER_WINDOW,
                 window_s: float = config.VOYAGE_WINDOW_SECONDS,
                 reserved_for_queries: int = config.RESERVED_FOR_QUERIES,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, poll_s: float = 0.5):
        assert 0 <= reserved_for_queries < per_window
        self.per_window, self.window_s = per_window, window_s
        self.reserved = reserved_for_queries
        self.clock, self.sleep, self.poll_s = clock, sleep, poll_s
        self._lock = threading.Lock()
        self._stamps: deque[float] = deque()  # completion times
        self._in_flight = 0

    def _capacity(self, priority: str) -> int:
        return self.per_window - (self.reserved if priority == "ingest" else 0)

    def acquire(self, priority: str = "ingest") -> float:
        """Block until a slot is free; return the seconds waited."""
        waited = 0.0
        while True:
            with self._lock:
                now = self.clock()
                while self._stamps and self._stamps[0] <= now - self.window_s:
                    self._stamps.popleft()
                if self._in_flight + len(self._stamps) < self._capacity(priority):
                    self._in_flight += 1
                    return waited
                # Wait for the oldest completed request to leave the window, or poll if every
                # slot is held by a request still in flight.
                wait = self._stamps[0] + self.window_s - now if self._stamps else self.poll_s
            wait = max(wait, 0.01)
            self.sleep(wait)
            waited += wait

    def release(self) -> None:
        with self._lock:
            self._in_flight -= 1
            self._stamps.append(self.clock())

    @contextmanager
    def slot(self, priority: str = "ingest"):
        waited = self.acquire(priority)
        try:
            yield waited
        finally:
            self.release()


VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
REQUEST_TIMEOUT_S = 60


class RateLimited(Exception):
    """Voyage answered 429 on every attempt."""


class VoyageEmbedder:
    """embed(texts, input_type) -> vectors. One call = one Voyage request.

    Calls the REST endpoint directly instead of the voyageai SDK: the SDK pulls in tokenizers,
    numpy, pillow and LangChain, which the API server doesn't need (counting tokens is an
    ingestion job). It also keeps retries in our hands, so no 429 is hidden.
    """

    def __init__(self, limiter: Limiter | None = None, model: str = config.EMBED_MODEL,
                 dim: int = config.EMBED_DIM, post=None, api_key: str | None = None,
                 sleep=time.sleep, log=print):
        self.limiter = limiter or Limiter()
        self.model, self.dim = model, dim
        self.space = f"{model}:{dim}:document"
        self.sleep, self.log = sleep, log
        self._post, self._api_key = post, api_key
        self.calls = 0  # requests sent, including rejected ones
        self.rate_limited = 0
        self.requests: list[tuple[float, float, int]] = []  # (start, end, n_texts), monotonic

    def _send(self, body: dict):
        if self._post is None:
            import requests

            self._post = requests.post
        if self._api_key is None:
            from dotenv import load_dotenv

            load_dotenv()
            self._api_key = os.environ["VOYAGE_API_KEY"]
        return self._post(VOYAGE_URL, json=body, timeout=REQUEST_TIMEOUT_S,
                          headers={"Authorization": f"Bearer {self._api_key}"})

    def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        priority = "query" if input_type == "query" else "ingest"
        body = {"input": texts, "model": self.model, "input_type": input_type,
                "output_dimension": self.dim, "truncation": False}
        for attempt in range(config.VOYAGE_MAX_RETRIES + 1):
            with self.limiter.slot(priority):
                start = time.monotonic()
                self.calls += 1
                response = self._send(body)
                if response.status_code != 429:
                    response.raise_for_status()  # anything else is a real error: stop
                    self.requests.append((start, time.monotonic(), len(texts)))
                    data = sorted(response.json()["data"], key=lambda d: d["index"])
                    return [d["embedding"] for d in data]
            self.rate_limited += 1
            if attempt == config.VOYAGE_MAX_RETRIES:
                raise RateLimited(f"429 on all {attempt + 1} attempts")
            self.log(f"  429 from Voyage (attempt {attempt + 1}); waiting "
                     f"{self.limiter.window_s:.0f} s (Voyage sends no Retry-After)")
            self.sleep(self.limiter.window_s)
        raise AssertionError("unreachable")
