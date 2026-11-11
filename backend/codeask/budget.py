"""The daily token budget (PLAN.md Q42, Q46): pure functions over the usage state that
`Store.usage(now)` returns, with the time passed in, so tests need no clock and no database.

Why a rolling 24 h: Groq's daily reset is undocumented. Counting the last 24 hourly buckets is
safe whatever the reset is, because tokens spent leave the window exactly 24 h later.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import NamedTuple

from codeask import config

WINDOW = timedelta(hours=24)


class Service(NamedTuple):
    status: str  # "ok" | "paused" | "daily_limit" (paused wins, Q45)
    retry_after_s: int | None = None  # whole seconds, only for daily_limit


def window_tokens(state: dict) -> int:
    return sum(tokens for _, tokens in state["buckets"])


def _seconds(delta: timedelta) -> int:
    return max(1, math.ceil(delta.total_seconds()))  # Retry-After is whole seconds, never 0


def service(state: dict, in_flight: int, now: datetime) -> Service:
    """Whether a new question may start. `in_flight` = questions accepted and not finished;
    each reserves QUESTION_RESERVE_TOKENS until its real usage is added."""
    if state["paused"]:
        return Service("paused")
    blocked = state["blocked_until"]
    if blocked is not None and now < blocked:
        return Service("daily_limit", _seconds(blocked - now))
    budget = state["public_budget_tokens"]
    need = config.QUESTION_RESERVE_TOKENS * (in_flight + 1)
    used = window_tokens(state)
    if used + need <= budget:
        return Service("ok")
    # When will enough leave the window? Oldest buckets go first, each 24 h after its hour.
    for hour, tokens in sorted(state["buckets"]):
        used -= tokens
        if used + need <= budget:
            return Service("daily_limit", _seconds(hour + WINDOW - now))
    # Only when the budget is below what the questions in flight reserve: their tokens land in
    # the current hour, so the honest answer is about a day.
    return Service("daily_limit", _seconds(WINDOW))


def tokens_used(usage: dict | None, groq_started: bool) -> int:
    """What one finished question adds to the budget: Groq's own count when it answered, an
    estimate when a request was sent but its outcome is unknown, else nothing."""
    if usage:
        total = usage.get("total_tokens")
        if isinstance(total, int):
            return total
        return int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0))
    return config.UNKNOWN_OUTCOME_TOKENS if groq_started else 0


def daily_block_until(retry_after_s: float, now: datetime) -> datetime | None:
    """A Groq 429 that asks for a long wait is the daily limit: no question can succeed until
    then, so it becomes `blocked_until` (Q46). A short wait is the per-minute limit: None."""
    if retry_after_s > config.DAILY_BLOCK_MIN_RETRY_S:
        return now + timedelta(seconds=retry_after_s)
    return None
