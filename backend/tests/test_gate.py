"""Admission for /ask and the usage copy for /status (PLAN.md Q44-Q46, step 6): the order of
checks, nothing counted on refusal, and a /status that never waits on the database."""

from datetime import datetime, timezone

from codeask import config
from codeask.api.gate import Refused, UsageCache, admit
from codeask.askqueue import AskQueue, Pacer
from codeask.askqueue import Ticket as QueueTicket
from codeask.visitors import Refusal, Ticket, Visitors

NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
RESERVE = config.QUESTION_RESERVE_TOKENS


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now


class OpenPacer(Pacer):
    def next_start(self, now):
        return now


def state(**changes):
    return {"public_budget_tokens": 120_000, "per_ip_daily": 5, "paused": False,
            "blocked_until": None, "buckets": [], **changes}


def make(pacer=None):
    clock = Clock()
    return Visitors(clock=clock), AskQueue(pacer or OpenPacer(), clock=clock), clock


def go(s, visitors, queue, clock, key="a"):
    return admit(s, key, visitors, queue, clock.now + 90, NOW, clock.now)


def busy_queue(clock):
    """A real pacer with one question running: a newcomer is projected past 60 s."""
    queue = AskQueue(Pacer(), clock=clock)
    running = queue.join("someone", clock.now + 90, clock.now)
    assert queue.try_start(running, clock.now)
    return queue


# ---------- each refusal, and nothing counted ----------
def test_accepted_holds_a_visitor_ticket_and_a_queue_place():
    visitors, queue, clock = make()
    result = go(state(), visitors, queue, clock)
    assert isinstance(result[0], Ticket) and isinstance(result[1], QueueTicket)
    assert queue.count() == 1
    assert visitors.check("a", 5).code == "in_progress"


def test_paused_has_no_retry_after():
    visitors, queue, clock = make()
    assert go(state(paused=True), visitors, queue, clock) == Refused(503, "paused", None)


def test_budget_refusal_is_daily_limit_and_counts_nothing():
    visitors, queue, clock = make()
    result = go(state(public_budget_tokens=RESERVE - 1), visitors, queue, clock)
    assert result.status == 429 and result.code == "daily_limit" and result.retry_after_s > 0
    assert visitors.check("a", 1) is None  # not charged
    assert queue.count() == 0


def test_the_budget_counts_every_ticket_in_the_line_as_in_flight():
    visitors, queue, clock = make()
    tight = state(public_budget_tokens=2 * RESERVE)  # room for exactly two
    assert not isinstance(go(tight, visitors, queue, clock, "a"), Refused)
    assert not isinstance(go(tight, visitors, queue, clock, "b"), Refused)
    assert go(tight, visitors, queue, clock, "c").code == "daily_limit"


def test_queue_busy_is_503_with_retry_after_and_counts_nothing():
    visitors, _, clock = make()
    queue = busy_queue(clock)
    result = go(state(), visitors, queue, clock)
    assert result == Refused(503, "busy", 19)  # projected 78 s: 78 - 60 + 1
    assert visitors.check("a", 1) is None
    assert queue.count() == 1  # only the running one


def test_a_visitor_racing_past_check_leaves_the_queue():
    class Racing(Visitors):
        def check(self, key, daily_limit):
            return None  # the other request hadn't been accepted yet

        def accept(self, key, daily_limit, deadline):
            return Refusal("in_progress", 30)

    _, queue, clock = make()
    result = go(state(), Racing(clock=clock), queue, clock)
    assert result == Refused(429, "in_progress", 30)
    assert queue.count() == 0


# ---------- the order (Q44): kill switch, in flight, per IP, budget, busy ----------
def test_paused_comes_before_everything():
    visitors, _, clock = make()
    visitors.accept("a", 5, clock.now + 30)  # also in flight
    s = state(paused=True, per_ip_daily=0, public_budget_tokens=0)
    assert go(s, visitors, busy_queue(clock), clock).code == "paused"


def test_in_flight_comes_before_the_daily_limits_and_busy():
    visitors, _, clock = make()
    visitors.accept("a", 5, clock.now + 30)
    s = state(per_ip_daily=0, public_budget_tokens=0)
    assert go(s, visitors, busy_queue(clock), clock) == Refused(429, "in_progress", 30)


def test_per_ip_comes_before_the_budget_and_the_budget_before_busy():
    visitors, _, clock = make()
    s = state(per_ip_daily=0, public_budget_tokens=0)
    assert go(s, visitors, busy_queue(clock), clock).code == "per_ip_limit"
    assert go(state(public_budget_tokens=0), visitors, busy_queue(clock), clock).code \
        == "daily_limit"


# ---------- the usage copy /status reads ----------
class Starter:
    """Collects background refreshes instead of starting threads."""

    def __init__(self):
        self.pending = []

    def __call__(self, fn):
        self.pending.append(fn)

    def run(self):
        while self.pending:
            self.pending.pop(0)()


def cache(load):
    clock, starter = Clock(), Starter()
    return UsageCache(load, clock=clock, max_age_s=30, start=starter), clock, starter


def test_no_copy_yet_answers_none_and_starts_one_refresh():
    usage, _, starter = cache(lambda: state())
    assert usage.get() is None
    assert usage.get() is None
    assert len(starter.pending) == 1  # single-flight
    starter.run()
    assert usage.get() == state()


def test_a_fresh_copy_needs_no_database_and_a_stale_one_refreshes_in_the_background():
    loads = []
    usage, clock, starter = cache(lambda: loads.append(1) or state(paused=True))
    usage.put(state())  # from an /ask
    clock.now += 29.9
    assert usage.get() == state() and not starter.pending
    clock.now += 0.1
    assert usage.get() == state()  # the stale copy is served at once...
    starter.run()  # ...and replaced in the background
    assert usage.get() == state(paused=True)
    assert loads == [1]


def test_a_failed_refresh_keeps_the_stale_copy_and_may_try_again():
    def broken():
        raise ConnectionError("host=secret")

    usage, clock, starter = cache(broken)
    usage.put(state())
    clock.now += 31
    usage.get()
    starter.run()
    assert usage.get() == state()  # kept
    assert len(starter.pending) == 1  # the next get may try again
