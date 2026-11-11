"""Per-visitor limits (PLAN.md Q44, Q46): one question in flight, and `per_ip_daily` questions
over a rolling 24 h, counted in memory under a salted hash of the client IP.

- In memory: the API is one process. A restart forgets the counts, which only errs toward
  letting a visitor in; the token budget (in the database) still protects the day.
- A salted HMAC, never the raw IP: nothing stored or logged can be turned back into an address,
  because hashing all 4 billion IPv4 addresses is useless without the secret salt.
- IPv6 by its /64: one home or phone usually gets a whole /64, so keying the full address would
  let one visitor rotate through 2^64 of them.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import threading
import time
from dataclasses import dataclass
from typing import NamedTuple

DAY_S = 24 * 3600
UNKNOWN = "unknown"  # the one shared bucket for requests without a usable client IP (Q6b)


def client_key(header: str | None, salt: bytes) -> str:
    """`CF-Connecting-IP` -> a salted hash, or UNKNOWN when it's missing or not an address."""
    try:
        ip = ipaddress.ip_address((header or "").strip())
    except ValueError:
        return UNKNOWN
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped  # ::ffff:1.2.3.4 is the IPv4 visitor 1.2.3.4
    if isinstance(ip, ipaddress.IPv6Address):
        text = str(ipaddress.ip_network(f"{ip}/64", strict=False))
    else:
        text = str(ip)
    return hmac.new(salt, text.encode(), hashlib.sha256).hexdigest()[:32]


class Refusal(NamedTuple):
    code: str  # "in_progress" | "per_ip_limit"
    retry_after_s: int


@dataclass(frozen=True, eq=False)  # identity, not value: two tickets are never the same one
class Ticket:
    key: str
    at: float  # when it was accepted (the clock's seconds)
    deadline: float  # when its /ask gives up: the in_progress Retry-After counts down to it


def _seconds(delta: float) -> int:
    return max(1, math.ceil(delta))


class Visitors:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._times: dict[str, list[float]] = {}  # accepted questions per key, oldest first
        self._in_flight: dict[str, Ticket] = {}

    def check(self, key: str, daily_limit: int) -> Refusal | None:
        """Read-only, so /ask can check in Q44's order and count nothing until acceptance."""
        with self._lock:
            return self._refusal(key, daily_limit, self.clock())

    def accept(self, key: str, daily_limit: int, deadline: float) -> Ticket | Refusal:
        """Checks again and records, atomically: two requests from one visitor can't both pass."""
        with self._lock:
            now = self.clock()
            refusal = self._refusal(key, daily_limit, now)
            if refusal:
                return refusal
            ticket = Ticket(key, now, deadline)
            self._times.setdefault(key, []).append(now)
            self._in_flight[key] = ticket
            return ticket

    def finish(self, ticket: Ticket, refund: bool = False) -> None:
        """Always called once the question ends. `refund` when it failed on our side (Q44):
        the visitor gets the question back. A second call for the same ticket does nothing."""
        with self._lock:
            if self._in_flight.get(ticket.key) is not ticket:
                return
            del self._in_flight[ticket.key]
            times = self._times.get(ticket.key)
            if refund and times and ticket.at in times:
                times.remove(ticket.at)

    def _refusal(self, key: str, daily_limit: int, now: float) -> Refusal | None:
        self._evict(now)
        ticket = self._in_flight.get(key)
        if ticket:
            return Refusal("in_progress", _seconds(ticket.deadline - now))
        times = self._times.get(key, [])
        if daily_limit <= 0:
            return Refusal("per_ip_limit", DAY_S)
        if len(times) >= daily_limit:
            # The visitor may ask again once enough old questions leave the 24 h window.
            return Refusal("per_ip_limit", _seconds(times[len(times) - daily_limit] + DAY_S - now))
        return None

    def _evict(self, now: float) -> None:
        cutoff = now - DAY_S
        for key in list(self._times):
            kept = [t for t in self._times[key] if t > cutoff]
            if kept:
                self._times[key] = kept
            else:
                del self._times[key]  # memory stays bounded by the last day's visitors
