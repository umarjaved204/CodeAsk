"""The /ask queue and its pacer (PLAN.md Q10, Q46 C1-C3 and the step 5 amendment).

One FIFO line over the whole /ask path, in process, under one `threading.Condition`. Only the
first waiting ticket may start, and only when the pacer says Groq and Voyage can take one more
question without a 429:

- Groq output tokens: qwen allows 1,000 output tokens a minute (not in the headers) and rejects
  outright a request whose `max_completion_tokens` (600) exceeds what is left ("Request too
  large"). So the question about to start counts its own 600 too:
  `recent output + 600 x (running + 1) <= 1,000`, which means at most one question runs at once.
- Groq tokens per minute: the last chat response's headers minus our own 3.5K estimate per
  question started since; once `reset-tokens` has passed (or with no usable headers), the limit
  minus the estimates for questions still running.
- Voyage: a read-only peek at the embedder's shared Limiter; the embedder takes the slot itself.

The wait estimate (`wait_s`, busy, Retry-After) is a projection: the same gates run forward on a
copy of the pacer, with every unfinished answer assumed as long and as large as the recent
maxima. It replaced an average gap between starts, which the burst test showed too low exactly
when it mattered (step 5 amendment 2: the gaps are ~10 s or ~63 s, never their mean).

Lock order: the queue's lock may take the Limiter's lock (the peek), never the reverse; the
Limiter knows nothing of this module.

The pure core (`join`, `try_start`, `leave`, `position`, `busy`) takes `now` and never sleeps,
so tests drive it with a fake clock and no threads. `wait_turn` is the only code that blocks.
Every clock here (the queue's, the Limiter's, the deadline's) is the same monotonic clock.
"""

from __future__ import annotations

import copy
import math
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import NamedTuple

from codeask import config
from codeask.deadline import DeadlineExceeded

_NUMBER = r"(\d+(?:\.\d+)?)"
_DURATION = re.compile(rf"(?:{_NUMBER}h)?(?:{_NUMBER}m(?!s))?(?:{_NUMBER}s)?(?:{_NUMBER}ms)?")


def parse_duration(text) -> float | None:
    """Groq's reset format ("7.66s", "2m59.56s", "1h2m", "500ms") -> seconds; None if unknown."""
    match = _DURATION.fullmatch(text.strip()) if isinstance(text, str) else None
    if not match or not any(match.groups()):
        return None
    h, m, s, ms = (float(g) if g else 0.0 for g in match.groups())
    return h * 3600 + m * 60 + s + ms / 1000


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class Pacer:
    """May one more question start? Pure apart from its own state: `now` is passed in."""

    def __init__(self, limiter=None):
        self.limiter = limiter  # the embedder's Limiter (same clock); None = no Voyage gate
        self.running = 0
        self.outputs: list[tuple[float, int]] = []  # (when it finished, output tokens), in order
        self.limit = config.GROQ_TOKENS_PER_MINUTE
        self.remaining: int | None = None  # tokens left this minute, per the last headers
        self.reset_at: float | None = None  # when those headers say the minute is full again
        self.unreflected = 0  # questions started that those headers don't include

    def start(self) -> None:
        self.running += 1
        self.unreflected += 1

    def finish(self, now: float, output_tokens: int, headers: dict | None) -> None:
        """Trues up a running question: its 600 reserve becomes the real output tokens,
        stamped when it finished (later than Groq counts them, so conservative)."""
        self.running -= 1
        self.outputs.append((now, output_tokens))
        if headers:  # only chat responses come here, never the model check's (other meaning)
            self._read_headers(headers, now)

    def _read_headers(self, headers: dict, now: float) -> None:
        limit = _int(headers.get("x-ratelimit-limit-tokens"))
        if limit is not None:
            self.limit = limit
        remaining = _int(headers.get("x-ratelimit-remaining-tokens"))
        reset = parse_duration(headers.get("x-ratelimit-reset-tokens"))
        if remaining is None or reset is None:
            self.remaining = self.reset_at = None  # unusable: as if there were none
        else:  # reset is from receipt: the headers are slightly older, so this errs late
            self.remaining, self.reset_at = remaining, now + reset
        self.unreflected = self.running  # questions still running aren't in these headers

    def next_start(self, now: float) -> float | None:
        """The earliest time (>= now) one more question may start if nothing else changes; None
        while only a running question finishing can open a gate."""
        times = [now]
        # Output tokens: the newcomer's 600 counts too ("Request too large" otherwise).
        allowed = (config.GROQ_OUTPUT_TOKENS_PER_MINUTE
                   - config.ANSWER_MAX_TOKENS * (self.running + 1))
        if allowed < 0:
            return None
        self.outputs = [(t, n) for t, n in self.outputs if t > now - config.OUTPUT_WINDOW_S]
        recent = sum(n for _, n in self.outputs)
        for t, n in self.outputs:  # oldest first: wait until enough of them age out
            if recent <= allowed:
                break
            recent -= n
            times.append(t + config.OUTPUT_WINDOW_S)
        # Tokens per minute: ~3.5K more must fit (Groq's refill within the minute is ignored).
        need = config.QUESTION_RESERVE_TOKENS
        full_minute = self.limit - need * self.running
        if self.reset_at is not None and now < self.reset_at:
            if self.remaining - need * self.unreflected < need:
                if full_minute < need:
                    return None
                times.append(self.reset_at)
        elif full_minute < need:
            return None
        # Voyage
        if self.limiter is not None:
            ready = self.limiter.ready_at("query")
            if ready is None:
                return None
            times.append(ready)
        return max(times)

    def ready(self, now: float) -> bool:
        at = self.next_start(now)
        return at is not None and at <= now


WAITING, RUNNING, LEFT = "waiting", "running", "left"


@dataclass(eq=False)  # identity, not value: two tickets are never the same one
class Ticket:
    key: str  # the visitor's hashed IP: /status finds "my question" by it (Q40)
    deadline: float
    joined_at: float
    state: str = WAITING
    started_at: float | None = None


class Busy(NamedTuple):
    retry_after_s: int


class AskQueue:
    def __init__(self, pacer: Pacer, clock=time.monotonic):
        self.pacer, self.clock = pacer, clock
        self._cond = threading.Condition()
        self._waiting: list[Ticket] = []  # in arrival order: [0] is the head
        self._running: list[Ticket] = []
        self._outputs_seen: deque[int] = deque(maxlen=config.PROJECTION_HISTORY)
        self._services_seen: deque[float] = deque(maxlen=config.PROJECTION_HISTORY)

    def count(self) -> int:
        """Questions accepted and not finished (the budget reserves tokens for each)."""
        with self._cond:
            return len(self._waiting) + len(self._running)

    def projected_output(self) -> int:
        """X: the most output tokens a recent answer used, never below the seed or above 600."""
        return min(config.ANSWER_MAX_TOKENS,
                   max([config.PROJECTED_OUTPUT_SEED, *self._outputs_seen]))

    def projected_service(self) -> float:
        """S: the longest a recent answer took, never below the seed or above 60 s. A few fast
        answers say little about the slowest, so like X it can't drop below its seed (step 5
        amendment 3: letting it drop made a retry at Retry-After refused again)."""
        longest = max([config.PROJECTED_SERVICE_SEED_S, *self._services_seen])
        return min(config.PROJECTED_SERVICE_MAX_S, longest)

    def _projection(self, now: float) -> list[float]:
        """The projected start of each waiting ticket, in order, then of a newcomer: the real
        gate code run forward on a copy of the pacer, each unfinished answer assumed to take S
        seconds and X output tokens. High values, not means: the output gate is a threshold
        (<= 400 recent), so a mean says "starts at once" exactly when a 63 s wait can still
        come. When outputs <= X and services <= S, this is an upper bound."""
        out, service = self.projected_output(), self.projected_service()
        pacer = copy.copy(self.pacer)  # every field is immutable except the stamps list
        pacer.outputs = list(self.pacer.outputs)
        pacer.limiter = None
        # Voyage bounds only the first start: later projected starts are ~63 s apart (X > 400
        # blocks each next start until it ages out), so they can't fill a 65 s window of 3.
        voyage = self.pacer.limiter.ready_at("query") if self.pacer.limiter else None
        finishes = sorted(t.started_at + service if t.started_at + service > now
                          else now + config.OVERDUE_MARGIN_S  # slow, not finishing "now"
                          for t in self._running)
        t, starts = now, []
        for _ in range(len(self._waiting) + 1):
            while True:  # finish the answers due before the next start could happen
                at = pacer.next_start(t)
                if finishes and (at is None or finishes[0] <= at):
                    t = max(t, finishes.pop(0))
                    pacer.finish(t, out, None)
                    continue
                break
            if at is None:  # no gate can ever open (a limit below one question): never
                return starts + [math.inf] * (len(self._waiting) + 1 - len(starts))
            t = max(at, voyage) if voyage is not None and not starts else at
            pacer.start()  # also deducts its 3.5K from the tokens-per-minute gate
            starts.append(t)
            finishes = sorted(finishes + [t + service])
        return starts

    def busy(self, now: float) -> Busy | None:
        """Would a newcomer be refused right now? Read-only."""
        with self._cond:
            wait = self._projection(now)[-1] - now
            if wait <= config.QUEUE_BUSY_WAIT_S and self.count() < config.QUEUE_MAX_TICKETS:
                return None
            if math.isinf(wait):
                return Busy(config.QUEUE_BUSY_WAIT_S)
            # Once this passes, a newcomer's projected wait is <= 60 (+1 s: no tie at the edge).
            return Busy(max(1, math.ceil(wait - config.QUEUE_BUSY_WAIT_S) + 1))

    def join(self, key: str, deadline: float, now: float) -> Ticket | Busy:
        with self._cond:
            refusal = self.busy(now)
            if refusal:
                return refusal
            ticket = Ticket(key, deadline, now)
            self._waiting.append(ticket)
            return ticket

    def position(self, key: str, now: float) -> tuple[int, int | None] | None:
        """(position, wait_s) for /status: 1 = being answered; None once the ticket has left.
        wait_s is an upper bound (None if it can't be projected)."""
        with self._cond:
            if any(t.key == key for t in self._running):
                return 1, 0
            for i, t in enumerate(self._waiting):
                if t.key == key:
                    start = self._projection(now)[i]
                    return i + 2, None if math.isinf(start) else math.ceil(max(0, start - now))
            return None

    def try_start(self, ticket: Ticket, now: float) -> bool:
        """Starts the ticket if it is the head and the pacer allows it. Raises DeadlineExceeded
        (and removes it) once it has too little time left to be worth starting."""
        with self._cond:
            if ticket.state != WAITING:
                return ticket.state == RUNNING
            if ticket.deadline - now < config.MIN_TIME_TO_START_S:
                self._waiting.remove(ticket)
                ticket.state = LEFT
                self._cond.notify_all()
                raise DeadlineExceeded  # nothing spent: 0 tokens, the visitor is refunded
            if self._waiting[0] is not ticket or not self.pacer.ready(now):
                return False
            self._waiting.pop(0)
            self._running.append(ticket)
            ticket.state, ticket.started_at = RUNNING, now
            self.pacer.start()
            self._cond.notify_all()  # the next ticket is now the head
            return True

    def leave(self, ticket: Ticket, now: float, completion_tokens: int | None = None,
              headers: dict | None = None, groq_started: bool = False) -> None:
        """Always called once the question ends, however it ends; the first call wins.
        `completion_tokens` is Groq's usage when it answered; without it a question that
        reached Groq keeps its 600 reserve, and one that never did counts 0."""
        with self._cond:
            if ticket.state == WAITING:
                self._waiting.remove(ticket)
            elif ticket.state == RUNNING:
                self._running.remove(ticket)
                if completion_tokens is not None:  # answered: teaches the projection's X and S
                    self._outputs_seen.append(completion_tokens)
                    self._services_seen.append(now - ticket.started_at)
                else:
                    completion_tokens = config.ANSWER_MAX_TOKENS if groq_started else 0
                self.pacer.finish(now, completion_tokens, headers)
            else:
                return
            ticket.state = LEFT
            self._cond.notify_all()

    def wait_turn(self, ticket: Ticket) -> None:
        """Blocks until the ticket starts; raises DeadlineExceeded if it runs out of time."""
        with self._cond:
            while True:
                now = self.clock()
                if self.try_start(ticket, now):
                    return
                timeout = min(config.WAIT_POLL_CAP_S,
                              ticket.deadline - config.MIN_TIME_TO_START_S - now)
                if self._waiting and self._waiting[0] is ticket:
                    at = self.pacer.next_start(now)
                    if at is not None:
                        timeout = min(timeout, at - now)
                self._cond.wait(max(0.01, timeout))  # never a zero or negative wait
