"""Per-visitor limits (PLAN.md Q44, Q46): pure, with a fake clock."""

from codeask.visitors import DAY_S, UNKNOWN, Refusal, Ticket, Visitors, client_key

SALT = b"test-salt"


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now


def make():
    clock = Clock()
    return Visitors(clock=clock), clock


def ask(visitors, clock, key="a", limit=5, takes=10.0, refund=False):
    """One question that is accepted, runs for `takes` seconds and ends."""
    ticket = visitors.accept(key, limit, deadline=clock.now + 90)
    assert isinstance(ticket, Ticket)
    clock.now += takes
    visitors.finish(ticket, refund=refund)


# ---------- the key ----------
def test_the_key_is_a_salted_hash_never_the_address():
    key = client_key("203.0.113.7", SALT)
    assert "203.0.113.7" not in key and len(key) == 32
    assert key == client_key(" 203.0.113.7 ", SALT)
    assert key != client_key("203.0.113.7", b"other-salt")  # useless without the salt
    assert key != client_key("203.0.113.8", SALT)


def test_ipv6_is_keyed_by_its_64_and_mapped_ipv4_is_the_ipv4_visitor():
    assert client_key("2001:db8:1:2::1", SALT) == client_key("2001:db8:1:2:ffff::9", SALT)
    assert client_key("2001:db8:1:2::1", SALT) != client_key("2001:db8:1:3::1", SALT)
    assert client_key("::ffff:203.0.113.7", SALT) == client_key("203.0.113.7", SALT)


def test_a_missing_or_garbage_header_is_the_shared_unknown_bucket():
    for header in (None, "", "not-an-ip", "203.0.113.7, 10.0.0.1"):
        assert client_key(header, SALT) == UNKNOWN


# ---------- one in flight ----------
def test_a_second_question_while_the_first_runs_is_in_progress_until_its_deadline():
    visitors, clock = make()
    first = visitors.accept("a", 5, deadline=clock.now + 90)
    clock.now += 30
    assert visitors.check("a", 5) == Refusal("in_progress", 60)
    assert visitors.accept("a", 5, deadline=clock.now + 90) == Refusal("in_progress", 60)
    assert visitors.check("b", 5) is None  # other visitors are unaffected
    visitors.finish(first)
    assert visitors.check("a", 5) is None


# ---------- the daily limit ----------
def test_five_a_day_then_refused_until_the_oldest_leaves_the_24_hours():
    visitors, clock = make()
    start = clock.now
    for _ in range(5):
        ask(visitors, clock)  # accepted at start, +10, +20, +30, +40
    assert visitors.check("a", 5) == Refusal("per_ip_limit", int(start + DAY_S - clock.now))
    clock.now = start + DAY_S  # the first question leaves the window
    assert visitors.check("a", 5) is None
    ask(visitors, clock, takes=0)  # at start + DAY_S: only the first has left, 5 counted again
    assert visitors.check("a", 5).code == "per_ip_limit"


def test_a_lower_limit_applies_at_once_and_counts_back_from_the_newest_that_still_fit():
    visitors, clock = make()
    start = clock.now
    for _ in range(5):
        ask(visitors, clock)
    # Limit 3 with 5 counted: asking again needs 3 to leave, the third oldest at start + 20.
    assert visitors.check("a", 3) == Refusal("per_ip_limit", int(start + 20 + DAY_S - clock.now))
    assert visitors.check("a", 0) == Refusal("per_ip_limit", DAY_S)


def test_a_failure_on_our_side_is_refunded_and_finish_twice_refunds_once():
    visitors, clock = make()
    for _ in range(4):
        ask(visitors, clock)
    ticket = visitors.accept("a", 5, deadline=clock.now + 90)
    visitors.finish(ticket, refund=True)
    visitors.finish(ticket, refund=True)
    assert visitors.check("a", 5) is None  # 4 counted: the refunded one is back
    ask(visitors, clock)
    assert visitors.check("a", 5).code == "per_ip_limit"  # and refunds stopped there


def test_old_visitors_are_evicted_after_a_day():
    visitors, clock = make()
    ask(visitors, clock, key="a")
    ask(visitors, clock, key="b")
    clock.now += DAY_S
    visitors.check("c", 5)
    assert visitors._times == {}
