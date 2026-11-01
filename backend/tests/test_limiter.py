from codeask.embedder import Limiter


class FakeClock:
    """Time only moves when the limiter sleeps, so tests run instantly and exactly."""

    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def make(**kwargs):
    clock = FakeClock()
    return Limiter(per_window=3, window_s=65, clock=clock, sleep=clock.sleep, **kwargs), clock


def test_three_requests_go_immediately_fourth_waits_a_window_after_completion():
    limiter, clock = make()
    for _ in range(3):
        assert limiter.acquire() == 0
        clock.now += 2  # each request takes 2 s
        limiter.release()  # stamped at completion: t = 2, 4, 6
    assert clock.now == 6
    waited = limiter.acquire()
    # The first slot frees 65 s after the first COMPLETION (t=2), not after its send (t=0).
    assert clock.now == 67
    assert waited == 61


def test_in_flight_requests_hold_their_slots():
    limiter, clock = make(poll_s=1)
    for _ in range(3):
        limiter.acquire()  # three requests in flight, none completed
    # A fourth caller can't proceed; with no completion stamps it polls. Release one after
    # the first poll by making sleep complete a request.
    original_sleep = clock.sleep

    def sleep_then_complete(seconds):
        original_sleep(seconds)
        if len(clock.slept) == 1:
            limiter.release()  # completes at t=1, frees at t=66

    limiter.sleep = sleep_then_complete
    limiter.acquire()
    assert clock.now == 66


def test_reserved_slots_are_for_queries_only():
    limiter, clock = make(reserved_for_queries=1)
    limiter.acquire("ingest")
    limiter.release()
    limiter.acquire("ingest")
    limiter.release()
    assert clock.now == 0
    # Ingestion has used its 2 slots; a query can still take the reserved third one at once.
    assert limiter.acquire("query") == 0
    limiter.release()
    # Now ingestion must wait for its oldest slot to expire.
    limiter.acquire("ingest")
    assert clock.now == 65


def test_slot_context_manager_releases_on_error():
    limiter, clock = make()
    try:
        with limiter.slot():
            raise RuntimeError("request failed")
    except RuntimeError:
        pass
    assert limiter._in_flight == 0 and len(limiter._stamps) == 1
