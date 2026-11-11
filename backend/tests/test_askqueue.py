"""The /ask queue and pacer (PLAN.md Q46, step 5 amendments 1 and 2): the pure state machine
on a fake clock, the pre-registered burst simulation against a fake Groq that enforces the real
limits, and one real-thread smoke test.

The burst numbers for the review: pytest backend/tests/test_askqueue.py -k report -s
"""

import functools
import inspect
import random
import statistics
import threading
import time

import pytest

import codeask.embedder
from codeask import config
from codeask.askqueue import LEFT, RUNNING, AskQueue, Busy, Pacer, Ticket, parse_duration
from codeask.deadline import DeadlineExceeded
from codeask.embedder import Limiter, VoyageEmbedder
from codeask.embedder import RateLimited as VoyageRateLimited

FLOOR = config.MIN_TIME_TO_START_S


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class AlwaysReady(Pacer):
    """A pacer that never blocks, to test the line on its own."""

    def next_start(self, now):
        return now


@pytest.fixture
def no_busy(monkeypatch):
    """For tests of other rules that join behind a running answer, which is busy by design."""
    monkeypatch.setattr(config, "QUEUE_BUSY_WAIT_S", 10_000)


def make(pacer=None, limiter=False):
    clock = Clock()
    if pacer is None:
        pacer = Pacer(Limiter(per_window=3, window_s=65, clock=clock, sleep=clock.sleep)
                      if limiter else None)
    return AskQueue(pacer, clock=clock), clock


def join(queue, clock, key, deadline_s=config.ASK_DEADLINE_S):
    ticket = queue.join(key, clock.now + deadline_s, clock.now)
    assert isinstance(ticket, Ticket)
    return ticket


def headers(remaining, reset, limit="8000"):
    return {"x-ratelimit-limit-tokens": limit, "x-ratelimit-remaining-tokens": remaining,
            "x-ratelimit-reset-tokens": reset}


# ---------- Groq's reset format ----------
@pytest.mark.parametrize("text, seconds", [
    ("7.66s", 7.66), ("2m59.56s", 179.56), ("500ms", 0.5), ("1h2m", 3720), ("1m500ms", 60.5),
    (" 3s ", 3), ("", None), ("soon", None), ("5", None), (None, None), (7, None)])
def test_reset_durations_parse_and_anything_unknown_is_none(text, seconds):
    assert parse_duration(text) == (pytest.approx(seconds) if seconds is not None else None)


# ---------- the line ----------
def test_only_the_head_starts():
    queue, clock = make(AlwaysReady())
    a, b = join(queue, clock, "a"), join(queue, clock, "b")
    assert not queue.try_start(b, clock.now)  # the pacer would allow it; FIFO doesn't
    assert queue.try_start(a, clock.now)
    assert queue.try_start(b, clock.now)


def test_busy_at_the_ticket_cap(no_busy):
    queue, clock = make()
    for i in range(config.QUEUE_MAX_TICKETS):
        join(queue, clock, f"k{i}")
    assert isinstance(queue.join("one more", clock.now + 90, clock.now), Busy)
    assert config.QUEUE_MAX_TICKETS < 40  # shorter than the thread pool


def test_leave_is_idempotent_and_a_waiting_ticket_just_goes():
    queue, clock = make()
    a = join(queue, clock, "a")
    queue.try_start(a, clock.now)
    queue.leave(a, clock.now, completion_tokens=300)
    queue.leave(a, clock.now, completion_tokens=300)
    assert queue.pacer.running == 0
    assert len(queue.pacer.outputs) == 1
    b = join(queue, clock, "b")
    queue.leave(b, clock.now)
    assert b.state == LEFT
    assert queue.count() == 0


def test_a_head_that_leaves_before_starting_lets_the_next_start():
    # /ask: join succeeded, then visitors.accept refused (two requests from one IP racing).
    queue, clock = make(AlwaysReady())
    a, b = join(queue, clock, "same ip"), join(queue, clock, "other")
    queue.leave(a, clock.now)
    assert queue.try_start(b, clock.now)


def test_an_exception_while_running_still_empties_the_line():
    queue, clock = make()
    a = join(queue, clock, "a")
    with pytest.raises(ValueError):
        try:
            queue.wait_turn(a)
            raise ValueError("the pipeline failed")
        finally:
            queue.leave(a, clock.now)
    assert queue.count() == 0
    assert queue.pacer.running == 0


def test_a_voyage_429_and_its_retry_never_wedge_the_line():
    queue, clock = make(limiter=True)
    limiter = queue.pacer.limiter

    class TooMany:
        status_code = 429

    embedder = VoyageEmbedder(limiter=limiter, post=lambda *a, **k: TooMany(), api_key="k",
                              sleep=clock.sleep, log=lambda *_: None)
    a = join(queue, clock, "a")
    with pytest.raises(VoyageRateLimited):
        try:
            queue.wait_turn(a)
            embedder.embed(["q"], "query", deadline=a.deadline)  # 429, a 65 s wait, 429
        finally:
            queue.leave(a, clock.now, groq_started=False)
    assert embedder.calls == 2
    assert queue.count() == 0
    b = join(queue, clock, "b")
    assert queue.try_start(b, clock.now)  # one Voyage slot is still free; 0 output tokens


# ---------- the deadline ----------
def test_a_waiting_ticket_without_enough_time_left_leaves_and_the_next_moves_up(no_busy):
    queue, clock = make()
    a = join(queue, clock, "a")
    queue.try_start(a, clock.now)
    b = join(queue, clock, "b")
    clock.now += 5
    join(queue, clock, "c")
    clock.now = b.deadline - FLOOR + 0.01
    with pytest.raises(DeadlineExceeded):
        queue.try_start(b, clock.now)
    assert b.state == LEFT
    assert queue.position("c", clock.now)[0] == 2


def test_the_floor_stops_a_ready_head_from_starting():
    queue, clock = make()
    a = join(queue, clock, "a")
    clock.now = a.deadline - FLOOR + 1  # 24 s left: the pacer would allow it
    with pytest.raises(DeadlineExceeded):
        queue.try_start(a, clock.now)
    assert queue.pacer.running == 0  # never started: 0 tokens, refunded
    assert queue.count() == 0


def test_wait_turn_gives_up_on_time_on_the_real_clock(no_busy):
    queue = AskQueue(Pacer())
    now = time.monotonic()
    a = queue.join("a", now + 90, now)
    assert queue.try_start(a, now)  # running: the output gate blocks everyone else
    b = queue.join("b", now + FLOOR + 0.2, now)
    t0 = time.monotonic()
    with pytest.raises(DeadlineExceeded):
        queue.wait_turn(b)
    assert time.monotonic() - t0 < 2
    assert b.state == LEFT


# ---------- the pacer's gates ----------
def test_output_gate_counts_the_newcomer_trues_up_and_ages_out_at_63_s(no_busy):
    queue, clock = make()
    a = join(queue, clock, "a")
    assert queue.try_start(a, clock.now)
    b = join(queue, clock, "b")
    assert not queue.try_start(b, clock.now)  # 600 + 600 > 1,000: one at a time
    assert queue.pacer.next_start(clock.now) is None  # only a finish can open it
    clock.now += 10
    first_finish = clock.now
    queue.leave(a, clock.now, completion_tokens=334)
    assert queue.try_start(b, clock.now)  # 334 + 600 <= 1,000
    clock.now += 10
    queue.leave(b, clock.now, completion_tokens=334)  # 668 in the window
    c = join(queue, clock, "c")
    assert queue.pacer.next_start(clock.now) == first_finish + 63
    clock.now = first_finish + 62.9
    assert not queue.try_start(c, clock.now)
    clock.now = first_finish + 63
    assert queue.try_start(c, clock.now)


@pytest.mark.parametrize("groq_started, counted", [(True, 600), (False, 0)])
def test_a_failure_keeps_600_only_if_groq_was_called(no_busy, groq_started, counted):
    queue, clock = make()
    a = join(queue, clock, "a")
    queue.try_start(a, clock.now)
    queue.leave(a, clock.now, groq_started=groq_started)
    assert queue.pacer.outputs[-1][1] == counted
    b = join(queue, clock, "b")
    assert queue.try_start(b, clock.now) is (counted == 0)


def test_tpm_gate_uses_fresh_headers_then_the_full_minute_after_reset():
    pacer = Pacer()
    pacer.start()
    pacer.finish(10.0, 300, headers("3000", "7.66s"))
    assert pacer.next_start(10.0) == pytest.approx(17.66)  # 3,000 < 3,500 until the reset
    assert pacer.ready(17.66)  # after it: 8,000 - 0 running


@pytest.mark.parametrize("bad", [headers("3000", "soon"), headers("lots", "7s"),
                                 {"x-ratelimit-reset-tokens": "7s"}])
def test_unusable_headers_count_as_none(bad):
    pacer = Pacer()
    pacer.start()
    pacer.finish(10.0, 300, bad)
    assert pacer.ready(10.0)


def test_tpm_gate_subtracts_starts_since_the_headers_and_uses_the_limit_header(monkeypatch):
    monkeypatch.setattr(config, "GROQ_OUTPUT_TOKENS_PER_MINUTE", 100_000)  # TPM alone
    pacer = Pacer()
    pacer.start()
    pacer.finish(0.0, 300, headers("7500", "30s"))
    assert pacer.ready(1.0)
    pacer.start()  # 7,500 - 3,500 = 4,000: room for one more
    assert pacer.ready(1.0)
    pacer.start()  # 7,500 - 7,000: no; after the reset 8,000 - 2 x 3,500 = 1,000: still no
    assert pacer.next_start(1.0) is None
    small = Pacer()
    small.start()
    small.finish(0.0, 300, headers("0", "1s", limit="4000"))
    assert small.ready(1.0)  # the minute is full again: 4,000 - 0 running
    small.start()
    assert small.next_start(2.0) is None  # 4,000 - 3,500 < 3,500


def test_voyage_gate_peeks_at_the_limiter(no_busy):
    queue, clock = make(limiter=True)
    limiter = queue.pacer.limiter
    for _ in range(3):
        limiter.acquire("query")
    assert limiter.ready_at("query") is None  # three in flight
    limiter.release()  # stamped at 1,000
    assert limiter.ready_at("query") == 1_065
    clock.now += 2
    limiter.release()
    limiter.release()
    a = join(queue, clock, "a")
    assert queue.pacer.next_start(clock.now) == 1_065
    assert queue.position("a", clock.now) == (2, 63)  # the projection's lower bound too
    assert not queue.try_start(a, clock.now)
    clock.now = 1_065
    assert queue.try_start(a, clock.now)
    assert limiter.acquire("query") == 0  # the peek took no slot


def test_a_free_voyage_slot_lets_the_head_start_even_if_the_limiters_clock_is_ahead():
    # Step 9 regression: the limiter read its own clock, a few microseconds after the queue's
    # now, so "free" always lay just in the future and the head waited until its floor.
    clock = Clock()
    limiter = Limiter(per_window=3, window_s=65, clock=lambda: clock.now + 1e-6, sleep=clock.sleep)
    queue = AskQueue(Pacer(limiter), clock=clock)
    a = join(queue, clock, "a")
    assert queue.position("a", clock.now) == (2, 0)
    assert queue.try_start(a, clock.now)


def test_real_clocks_and_a_real_limiter_start_an_empty_line_at_once():
    queue = AskQueue(Pacer(Limiter()))  # time.monotonic everywhere, read at different moments
    now = time.monotonic()
    a = queue.join("a", now + 90, now)
    assert isinstance(a, Ticket)
    t0 = time.monotonic()
    queue.wait_turn(a)
    assert a.state == RUNNING
    assert time.monotonic() - t0 < 1


def test_the_limiter_never_calls_into_the_queue():
    # Lock order: the queue's lock (the projection included) may take the limiter's, never
    # the reverse.
    assert "askqueue" not in inspect.getsource(codeask.embedder)


# ---------- the wait projection (X = 460 and S = 15 s until answers are seen) ----------
def test_projection_positions_and_nothing_once_left(no_busy):
    queue, clock = make()
    a = join(queue, clock, "a")
    assert queue.position("a", clock.now) == (2, 0)  # waiting, but free to start now
    queue.try_start(a, clock.now)
    b, c = join(queue, clock, "b"), join(queue, clock, "c")
    assert queue.position("a", clock.now) == (1, 0)
    # a ends at 1,015 with 460 > 400 output tokens: b starts when they age out, 63 s later.
    assert queue.position("b", clock.now) == (2, 78)
    assert queue.position("c", clock.now) == (3, 156)  # b likewise: 1,093 + 63
    queue.leave(b, clock.now)
    assert queue.position("b", clock.now) is None
    assert queue.position("c", clock.now) == (2, 78)
    clock.now += 10
    queue.leave(a, clock.now, completion_tokens=300)  # the real answer: 300 tokens, 10 s
    assert queue.position("a", clock.now) is None
    assert queue.position("c", clock.now) == (2, 0)  # 300 <= 400: c may start at once
    assert queue.position("nobody", clock.now) is None


def test_a_running_answer_past_s_is_assumed_to_need_5_s_more(no_busy):
    queue, clock = make()
    a = join(queue, clock, "a")
    queue.try_start(a, clock.now)
    clock.now += 20  # past S = 15
    join(queue, clock, "b")
    assert queue.position("b", clock.now) == (2, 5 + 63)  # not "finishes now"


def test_x_and_s_are_recent_maxima_clamped():
    queue, clock = make(AlwaysReady())

    def answer(tokens, seconds):
        ticket = join(queue, clock, "k")
        queue.try_start(ticket, clock.now)
        clock.now += seconds
        queue.leave(ticket, clock.now, completion_tokens=tokens)

    assert (queue.projected_output(), queue.projected_service()) == (460, 15)  # the seeds
    answer(300, 3)
    assert (queue.projected_output(), queue.projected_service()) == (460, 15)  # never below
    answer(520, 18)
    assert (queue.projected_output(), queue.projected_service()) == (520, 18)
    answer(700, 80)
    assert (queue.projected_output(), queue.projected_service()) == (600, 60)  # clamped down
    a = join(queue, clock, "failed")
    queue.try_start(a, clock.now)
    clock.now += 100
    queue.leave(a, clock.now, groq_started=True)  # no answer: teaches neither
    assert queue.projected_service() == 60
    for _ in range(config.PROJECTION_HISTORY):
        answer(300, 3)
    assert (queue.projected_output(), queue.projected_service()) == (460, 15)  # forgotten


def test_the_projection_deducts_each_projected_start_from_the_tpm_gate(monkeypatch):
    monkeypatch.setattr(config, "GROQ_OUTPUT_TOKENS_PER_MINUTE", 100_000)  # TPM alone
    monkeypatch.setattr(config, "QUEUE_BUSY_WAIT_S", 10_000)
    queue, clock = make()
    for key in "abc":
        join(queue, clock, key)
    # Two fit in 8,000 (3,500 each); the third waits for the first to finish (S = 15 s).
    assert queue._projection(clock.now) == [1_000, 1_000, 1_015, 1_015]


def test_busy_retry_after_and_a_clean_retry_is_accepted():
    queue, clock = make()
    a = join(queue, clock, "a")  # an empty line, no history: admitted, starts at once
    queue.try_start(a, clock.now)
    assert queue.join("b", clock.now + 90, clock.now) == Busy(19)  # 78 - 60 + 1
    clock.now += 15
    queue.leave(a, clock.now, completion_tokens=460)  # within S and X
    clock.now = 1_019
    assert isinstance(queue.join("b", clock.now + 90, clock.now), Ticket)  # waits 59 s


def test_just_after_a_large_answer_even_an_empty_line_waits_for_it_to_age():
    queue, clock = make()
    a = join(queue, clock, "a")
    queue.try_start(a, clock.now)
    queue.leave(a, clock.now, completion_tokens=460)
    assert queue.join("b", clock.now + 90, clock.now) == Busy(4)  # 63 - 60 + 1
    clock.now += 4
    assert queue.position(join(queue, clock, "b").key, clock.now) == (2, 59)


# ---------- the burst (slice 4's Done-when proof, pre-registered in PLAN.md Q46) ----------
class FakeGroq:
    """Groq's real free-tier rules for qwen, with literal numbers so a config change can't make
    the fake agree with the pacer: 1,000 output tokens/min (a request whose possible output
    exceeds what's left is rejected) and 8,000 tokens/min (prompt + max output must fit)."""

    def __init__(self):
        self.tokens: list[tuple[float, int]] = []  # (request time, prompt + output)
        self.outputs: list[tuple[float, int]] = []  # (finish time, output)
        self.rejected = 0

    @staticmethod
    def _used(stamps, now):
        return sum(n for t, n in stamps if t > now - 60)

    def request(self, now, prompt, output) -> bool:
        if (self._used(self.outputs, now) + 600 > 1_000
                or self._used(self.tokens, now) + prompt + 600 > 8_000):
            self.rejected += 1
            return False
        self.tokens.append((now, prompt + output))
        return True

    def finish(self, now, output) -> dict:
        self.outputs.append((now, output))
        newest = max(t for t, _ in self.tokens)
        return headers(str(8_000 - self._used(self.tokens, now)),
                       f"{max(0.0, newest + 60 - now):.2f}s")


def realistic_output(rng):
    return min(460, max(150, round(rng.gauss(334, 60))))  # mean ~334, max 460 as measured


DISTS = {  # name -> (output tokens, service seconds)
    "realistic": (realistic_output, lambda rng: rng.uniform(3, 15)),
    "worst": (lambda rng: 460, lambda rng: rng.uniform(3, 15)),
    # Property tests: every answer exactly X and S (oracle), or never above them (bounded:
    # X can't fall below 460 nor S below 15 s, so these always hold).
    "oracle": (lambda rng: 460, lambda rng: 15),
    "bounded": (realistic_output, lambda rng: rng.uniform(3, 5)),
    # Informational: a wrong seed, 10% of answers take 20-40 s (above S = 15 s).
    "slow_tail": (realistic_output, lambda rng: rng.uniform(20, 40) if rng.random() < 0.1
                  else rng.uniform(3, 15)),
}


def simulate(seed, dist, arrivals=12, spread_s=20, admit_all=False):
    """A discrete-event run of one burst through the real queue and pacer. `admit_all` is the
    counterfactual for the false-busy measure: the same visitors, nobody refused."""
    rng = random.Random(seed)
    output_of, service_of = DISTS[dist]
    clock = Clock()

    def never_wait(seconds):
        raise AssertionError(f"Voyage made a started question wait {seconds} s")

    limiter = Limiter(per_window=3, window_s=65, clock=clock, sleep=never_wait)
    queue = AskQueue(Pacer(limiter), clock=clock)
    if admit_all:
        queue.busy = lambda now: None
    groq = FakeGroq()
    pending = list(enumerate(sorted(clock.now + rng.uniform(0, spread_s)
                                    for _ in range(arrivals))))
    # Drawn per visitor up front, so the counterfactual run gives each visitor the same answer.
    plan = [(output_of(rng), service_of(rng), rng.randint(2_300, 2_900))
            for _ in range(arrivals)]
    running = []  # (finish time, ticket, output)
    probes = []  # (time, admitted so far): a Busy's Retry-After, checked then
    tickets, info, starts = [], {}, []
    log = [None] * arrivals
    r = {"admitted": 0, "busy": 0, "timeouts": 0, "max_running": 0, "untruthful_retry": 0,
         "untruthful_retry_clean": 0, "retry_clean": 0, "refused_clean_overdue": 0,
         "past_deadline": 0, "over": [], "waits": [], "late_vs_projection": [],
         "late_vs_estimate": 0, "old_tolerance_misses": 0}
    for _ in range(100_000):
        due = [at for _, at in pending[:1]] + [f for f, _, _ in running] + [p for p, _ in probes]
        due += [t.deadline - FLOOR for t in queue._waiting]
        if queue._waiting:
            at = queue.pacer.next_start(clock.now)
            if at is not None:
                due.append(at)
        if not due:
            break
        clock.now = max(clock.now, min(due)) + 1e-6  # just past it: no float ties
        for item in [x for x in running if x[0] <= clock.now]:
            running.remove(item)
            _, ticket, output = item
            queue.leave(ticket, clock.now, output, groq.finish(clock.now, output))
        while pending and pending[0][1] <= clock.now:
            i, _ = pending.pop(0)
            key = f"v{i}"
            projected = queue._projection(clock.now)[-1]  # the newcomer's, before it joins
            got = queue.join(key, clock.now + config.ASK_DEADLINE_S, clock.now)
            if isinstance(got, Busy):
                r["busy"] += 1
                probes.append((clock.now + got.retry_after_s, r["admitted"]))
                log[i] = {"admitted": False, "retry_after": got.retry_after_s}
                continue
            r["admitted"] += 1
            tickets.append(got)
            log[i] = {"admitted": True, "wait": None, "started": False}
            info[id(got)] = (i, clock.now, projected, queue.position(key, clock.now)[1])
        for probe in [p for p in probes if p[0] <= clock.now]:
            probes.remove(probe)
            refused = queue.busy(clock.now) is not None
            r["untruthful_retry"] += refused
            if probe[1] == r["admitted"]:  # nobody else joined in between: a clean retry
                r["retry_clean"] += 1
                r["untruthful_retry_clean"] += refused
                if refused:  # the check the diagnosis rests on: an answer had run past S
                    r["refused_clean_overdue"] += any(
                        t.started_at + queue.projected_service() < clock.now
                        for t in queue._running)
        for ticket in list(queue._waiting):
            try:
                if not queue.try_start(ticket, clock.now):
                    continue
            except DeadlineExceeded:
                r["timeouts"] += 1
                continue
            i, joined, projected, estimate = info[id(ticket)]
            starts.append(i)
            actual = clock.now - joined
            log[i].update(wait=actual, started=True)
            r["waits"].append(actual)
            r["over"].append(estimate - actual)
            r["late_vs_projection"].append(clock.now - projected)
            r["late_vs_estimate"] += actual > estimate + 2
            r["old_tolerance_misses"] += abs(estimate - actual) > max(30, 0.5 * actual)
            limiter.acquire("query")
            limiter.release()  # the embedding (its time is part of the service time)
            output, service, prompt = plan[i]
            r["past_deadline"] += clock.now + service > ticket.deadline
            if groq.request(clock.now, prompt, output):
                running.append((clock.now + service, ticket, output))
            else:
                queue.leave(ticket, clock.now, groq_started=True)
        r["max_running"] = max(r["max_running"], len(queue._running))
    else:
        raise AssertionError("the simulation did not finish")
    r.update(rejected=groq.rejected, fifo=starts == sorted(starts), log=log,
             stuck=sum(t.state != LEFT for t in tickets), arrivals=arrivals)
    return r


SEEDS = range(200)


@functools.cache
def burst(dist, arrivals=12, spread_s=20, admit_all=False):
    return [simulate(seed, dist, arrivals, spread_s, admit_all) for seed in SEEDS]


SAFETY = ("rejections", "fifo", "over one running", "stuck")


def hard_failures(r):
    return {"rejections": r["rejected"] > 0, "fifo": not r["fifo"],
            "over one running": r["max_running"] > 1, "stuck": r["stuck"] > 0,
            "untruthful clean Retry-After": r["untruthful_retry_clean"] > 0}


@pytest.mark.parametrize("dist", ["realistic", "worst", "oracle", "bounded"])
def test_burst_hard_invariants_hold_in_every_seed(dist):
    for seed, r in zip(SEEDS, burst(dist)):
        assert r["admitted"] + r["busy"] == r["arrivals"], seed  # a position or Busy, each
        failed = [name for name, bad in hard_failures(r).items() if bad]
        assert not failed, (seed, failed)


def test_a_wrong_seed_degrades_without_breaking_safety():
    # slow_tail: informational (the report has its rates), but these must still hold.
    for seed, r in zip(SEEDS, burst("slow_tail")):
        failed = [name for name in SAFETY if hard_failures(r)[name]]
        assert not failed, (seed, failed)


def follow_up(seed, delay_s):
    """One visitor asks again `delay_s` after their first answer finished (realistic); the
    wait in seconds, or None if refused as busy."""
    rng = random.Random(seed)
    clock = Clock()
    limiter = Limiter(per_window=3, window_s=65, clock=clock, sleep=clock.sleep)
    queue = AskQueue(Pacer(limiter), clock=clock)
    groq = FakeGroq()
    first = join(queue, clock, "me")
    assert queue.try_start(first, clock.now)
    limiter.acquire("query")
    limiter.release()
    output = realistic_output(rng)
    assert groq.request(clock.now, rng.randint(2_300, 2_900), output)
    clock.now += rng.uniform(3, 15)
    queue.leave(first, clock.now, output, groq.finish(clock.now, output))
    clock.now += delay_s
    second = queue.join("me", clock.now + config.ASK_DEADLINE_S, clock.now)
    if isinstance(second, Busy):
        return None
    joined = clock.now
    while not queue.try_start(second, clock.now):  # DeadlineExceeded would fail the test
        clock.now = queue.pacer.next_start(clock.now) + 1e-6
    assert groq.request(clock.now, rng.randint(2_300, 2_900), realistic_output(rng))
    return clock.now - joined


@functools.cache
def follow_ups(delay_s):
    return [follow_up(seed, delay_s) for seed in SEEDS]


def test_a_follow_up_30_s_after_an_answer_is_never_busy_and_mostly_immediate():
    # Pre-registered (mentor, step 5): at 30 s, >= 80% start within 2 s and none is busy.
    waits = follow_ups(30)
    assert None not in waits
    assert sum(w <= 2 for w in waits) >= 0.8 * len(waits)


def test_projection_oracle_actual_start_equals_projected():
    for seed, r in zip(SEEDS, burst("oracle")):
        assert all(abs(late) <= 1 for late in r["late_vs_projection"]), seed


@pytest.mark.parametrize("dist", ["oracle", "bounded"])
def test_projection_is_an_upper_bound_when_its_assumptions_hold(dist):
    for seed, r in zip(SEEDS, burst(dist)):
        assert all(late <= 2 for late in r["late_vs_projection"]), seed


def test_burst_realistic_99_percent_start_by_their_estimate():
    runs = burst("realistic")
    started = sum(len(r["waits"]) for r in runs)
    assert sum(r["late_vs_estimate"] for r in runs) <= 0.01 * started


def test_burst_at_most_5_percent_of_admitted_time_out_realistic():
    runs = burst("realistic")
    assert sum(r["timeouts"] for r in runs) <= 0.05 * sum(r["admitted"] for r in runs)


def _report_burst(dist, arrivals, spread_s):
    runs = burst(dist, arrivals, spread_s)
    admitted = sum(r["admitted"] for r in runs)
    timeouts = sum(r["timeouts"] for r in runs)
    over = sorted(o for r in runs for o in r["over"])
    started = len(over)
    fails = {name: sum(hard_failures(r)[name] for r in runs) for name in hard_failures(runs[0])}
    print(f"\n[{dist}] {len(runs)} seeds x {arrivals} arrivals within {spread_s} s")
    print(f"  seeds failing each hard invariant: {fails}")
    print(f"  admitted {admitted}, busy {sum(r['busy'] for r in runs)} "
          f"({100 * sum(r['busy'] for r in runs) / (arrivals * len(runs)):.0f}% of arrivals), "
          f"timed out {timeouts} ({100 * timeouts / max(1, admitted):.1f}% of admitted)")
    print(f"  Retry-After refused at retry: clean {sum(r['untruthful_retry_clean'] for r in runs)}"
          f" of {sum(r['retry_clean'] for r in runs)}; all {sum(r['untruthful_retry'] for r in runs)}"
          f" of {sum(r['busy'] for r in runs)} (contested ones: reported, not asserted); "
          f"refused clean retries with an answer running past S: "
          f"{sum(r['refused_clean_overdue'] for r in runs)}")
    print(f"  started answers that would run past their deadline: "
          f"{sum(r['past_deadline'] for r in runs)}")
    if started >= 2:
        q = statistics.quantiles(over, n=20)
        late = [x for r in runs for x in r["late_vs_projection"]]
        print(f"  over-estimate (estimate - actual, s): median {statistics.median(over):.1f}, "
              f"p95 {q[-1]:.1f}, min {over[0]:.1f}, max {over[-1]:.1f}")
        print(f"  started later than estimate + 2 s: {sum(r['late_vs_estimate'] for r in runs)}"
              f" of {started}; latest vs projection {max(late):+.1f} s; old two-sided "
              f"tolerance misses {sum(r['old_tolerance_misses'] for r in runs)}")
        print(f"  longest wait before a start: {max(w for r in runs for w in r['waits']):.1f} s")


def _report_small(arrivals, spread_s):
    runs = burst("realistic", arrivals, spread_s)
    print(f"\n[realistic, {arrivals} visitors within {spread_s} s] {len(runs)} seeds")
    for i in range(1, arrivals):
        entries = [r["log"][i] for r in runs]
        admitted = [e for e in entries if e["admitted"]]
        waits = [e["wait"] for e in admitted if e["wait"] is not None]
        retries = [e["retry_after"] for e in entries if not e["admitted"]]
        text = f"  visitor {i + 1}: admitted in {len(admitted)} of {len(runs)} seeds"
        if waits:
            text += f", wait median {statistics.median(waits):.0f} s, max {max(waits):.0f} s"
        if retries:
            text += (f"; busy with Retry-After median {statistics.median(retries):.0f} s, "
                     f"max {max(retries)} s")
        print(text)


def _report_false_busy(dist):
    """Refused visitors who, with nobody refused, would have started in time (informational:
    admitting them also delays the others, so this overstates what was given up)."""
    refused = would_have_started = 0
    for real, everyone in zip(burst(dist), burst(dist, admit_all=True)):
        for mine, theirs in zip(real["log"], everyone["log"]):
            if not mine["admitted"]:
                refused += 1
                would_have_started += theirs["started"]
    print(f"  [{dist}] false busy: {would_have_started} of {refused} refused visitors would "
          f"have started in time with nobody refused")


def _report_follow_ups():
    print(f"\n[realistic, one visitor asks again after the first answer] {len(SEEDS)} seeds")
    for delay in (20, 30, 45):
        results = follow_ups(delay)
        waits = sorted(w for w in results if w is not None)
        busy = sum(w is None for w in results)
        text = f"  after {delay} s: busy {busy} of {len(results)}"
        if len(waits) >= 2:
            text += (f"; started within 2 s {sum(w <= 2 for w in waits)} of {len(waits)}, "
                     f"wait median {statistics.median(waits):.1f} s, "
                     f"p95 {statistics.quantiles(waits, n=20)[-1]:.1f} s")
        print(text)


def test_burst_report():
    """Not an assertion: the numbers PLAN.md asks for. Run with -s to see them."""
    for dist in DISTS:
        _report_burst(dist, 12, 20)
    print()
    for dist in ("realistic", "worst"):
        _report_false_busy(dist)
    _report_small(2, 5)
    _report_small(3, 10)
    _report_follow_ups()


# ---------- real threads ----------
def test_real_threads_start_in_order_and_the_line_ends_empty(no_busy):
    queue = AskQueue(Pacer())  # the real gates: one at a time, 0 output tokens each
    now = time.monotonic()
    tickets = [queue.join(f"k{i}", now + 90, now) for i in range(3)]
    assert all(isinstance(t, Ticket) for t in tickets)
    order, failed = [], []

    def run(ticket, fail):
        try:
            try:
                queue.wait_turn(ticket)
                order.append(ticket.key)
                assert ticket.state == RUNNING
                time.sleep(0.02)
                if fail:
                    raise ValueError("boom")
            finally:
                queue.leave(ticket, time.monotonic(), completion_tokens=0)
        except ValueError:
            failed.append(ticket.key)

    threads = [threading.Thread(target=run, args=(t, i == 1), daemon=True)
               for i, t in enumerate(tickets)]
    for thread in reversed(threads):  # start order mustn't matter: the line decides
        thread.start()
    deadline = time.monotonic() + 10  # a deadlock fails fast instead of hanging the suite
    for thread in threads:
        thread.join(max(0, deadline - time.monotonic()))
    assert not any(t.is_alive() for t in threads), "deadlock"
    assert order == ["k0", "k1", "k2"]
    assert failed == ["k1"]
    assert queue.count() == 0
