"""Who may ask now (PLAN.md Q44-Q46, step 6): the order of checks for /ask, the refund rule,
and the in-memory usage copy /status reads.

The order (Q44): kill switch -> previous question in flight -> per-IP daily -> token budget ->
queue busy. The read-only checks come first and nothing is counted until the question is
accepted, so a refused request costs the visitor nothing.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable, NamedTuple

from codeask import budget, config
from codeask.askqueue import AskQueue, Busy
from codeask.askqueue import Ticket as QueueTicket
from codeask.visitors import Refusal, Ticket, Visitors

log = logging.getLogger("uvicorn.error.codeask")

# Outcomes after acceptance that failed on our side, so the visitor gets the question back
# (Q44, step 6 decision 2). The other two outcomes after acceptance, "answered" and
# "ungrounded", are real, shown results and are not refunded.
REFUNDED = frozenset({
    "timeout",  # the deadline passed, in the queue or upstream
    "busy",  # Groq or Voyage said 429 after we had accepted the question
    "upstream_error", "database_unavailable", "internal_error",  # any 5xx
    "model_unavailable",  # Groq says the model is gone
    "daily_limit",  # Groq's own daily limit, met after acceptance
})


class Refused(NamedTuple):
    status: int
    code: str  # "paused" | "in_progress" | "per_ip_limit" | "daily_limit" | "busy"
    retry_after_s: int | None  # whole seconds; None for paused (nobody knows when it ends)


def admit(state: dict, key: str, visitors: Visitors, queue: AskQueue, deadline: float,
          wall_now: datetime, now: float) -> tuple[Ticket, QueueTicket] | Refused:
    """The order of checks. On acceptance the visitor and the queue each hold a ticket, and
    the caller must finish both, however the question ends."""
    if state["paused"]:
        return Refused(503, "paused", None)
    refusal = visitors.check(key, state["per_ip_daily"])
    if refusal:
        return Refused(429, refusal.code, refusal.retry_after_s)
    service = budget.service(state, queue.count(), wall_now)
    if service.status != "ok":  # only daily_limit can remain: paused was checked above
        return Refused(429, service.status, service.retry_after_s)
    place = queue.join(key, deadline, now)
    if isinstance(place, Busy):
        return Refused(503, "busy", place.retry_after_s)
    visit = visitors.accept(key, state["per_ip_daily"], deadline)
    if isinstance(visit, Refusal):  # two requests from one visitor raced past check()
        queue.leave(place, now)
        return Refused(429, visit.code, visit.retry_after_s)
    return visit, place


def _thread(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True).start()


class UsageCache:
    """The usage state /status reads, so /status never waits on the database (Q40, Q46 C4).
    Every /ask puts the row it read; a copy older than `max_age_s` is refreshed in the
    background, one refresh at a time; a failed refresh keeps the stale copy. Neon is then
    queried at most every 30 s, and only while someone is looking."""

    def __init__(self, load: Callable[[], dict], clock=time.monotonic,
                 max_age_s: float = config.USAGE_MAX_AGE_S, start=_thread):
        self.load, self.clock, self.max_age_s, self.start = load, clock, max_age_s, start
        self._lock = threading.Lock()
        self._state: dict | None = None
        self._at: float | None = None
        self._refreshing = False

    def put(self, state: dict) -> None:
        with self._lock:
            self._state, self._at = state, self.clock()

    def get(self) -> dict | None:
        """The latest copy (None before the first), starting a refresh if it's stale."""
        with self._lock:
            stale = self._at is None or self.clock() - self._at >= self.max_age_s
            refresh = stale and not self._refreshing
            if refresh:
                self._refreshing = True
            state = self._state
        if refresh:
            self.start(self._refresh)
        return state

    def _refresh(self) -> None:
        try:
            self.put(self.load())
        except Exception as exc:  # the stale copy stays; never the exception text (DB host)
            log.warning("usage refresh failed: %s", type(exc).__name__)
        finally:
            with self._lock:
                self._refreshing = False
