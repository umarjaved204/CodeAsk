"""One deadline per /ask (PLAN.md Q43): an absolute time on a monotonic clock, passed down to the
queue wait, the Voyage call and the Groq call.

Why one deadline instead of a timeout per step: per-step timeouts add up (60 s for Voyage plus
60 s for Groq plus the queue) past what the proxy allows, and a browser timeout wouldn't free the
server's thread. One deadline bounds the whole question. `None` means no deadline (ingestion, CLI).

`requests` timeouts bound each connect and each read, not the whole transfer, so a reply that
trickles in could overrun slightly; Groq and Voyage reply in one piece, so that's accepted.
"""

from __future__ import annotations

import time
from typing import Callable


class DeadlineExceeded(Exception):
    """The question's time ran out before a step could start or finish."""


def time_left(deadline: float | None, clock: Callable[[], float] = time.monotonic) -> float:
    return float("inf") if deadline is None else deadline - clock()


def timeout_for(cap: float, deadline: float | None,
                clock: Callable[[], float] = time.monotonic) -> float:
    """An HTTP timeout no longer than `cap` or the time left; raises if none is left."""
    left = time_left(deadline, clock)
    if left <= 0:
        raise DeadlineExceeded
    return min(cap, left)
