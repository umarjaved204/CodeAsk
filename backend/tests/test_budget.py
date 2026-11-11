"""The daily token budget (PLAN.md Q42, Q46): pure functions, no clock, no database."""

from datetime import datetime, timedelta, timezone

from codeask.budget import Service, daily_block_until, service, tokens_used

NOW = datetime(2026, 11, 11, 10, 30, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def state(buckets=(), budget=120_000, paused=False, blocked_until=None):
    return {"public_budget_tokens": budget, "per_ip_daily": 5, "paused": paused,
            "blocked_until": blocked_until, "buckets": list(buckets)}


# ---------- admission ----------
def test_a_question_is_admitted_while_its_reserve_fits():
    # 113,000 used + 3,500 for this question + 3,500 for the one in flight = 120,000 exactly.
    assert service(state([(NOW - 2 * HOUR, 113_000)]), 1, NOW) == Service("ok")
    assert service(state([(NOW - 2 * HOUR, 113_001)]), 1, NOW).status == "daily_limit"


def test_when_full_retry_after_is_when_enough_old_tokens_leave_the_window():
    hour_ago_23 = datetime(2026, 11, 10, 11, tzinfo=timezone.utc)  # leaves at 11:00 today
    hour_ago_20 = datetime(2026, 11, 10, 14, tzinfo=timezone.utc)  # leaves at 14:00 today
    buckets = [(hour_ago_20, 50_000), (hour_ago_23, 1_000), (NOW, 68_000)]
    # Dropping the 1,000 isn't enough (118,000 + 3,500 > 120,000); dropping both is.
    assert service(state(buckets), 0, NOW) == Service("daily_limit", int(3.5 * 3600))


def test_a_budget_below_the_reserve_alone_says_about_a_day():
    assert service(state(budget=3_000), 0, NOW) == Service("daily_limit", 24 * 3600)


def test_paused_wins_over_everything_and_gives_no_time():
    full = state([(NOW, 200_000)], paused=True, blocked_until=NOW + HOUR)
    assert service(full, 0, NOW) == Service("paused")


def test_a_daily_block_from_groq_holds_until_its_time_then_lapses():
    blocked = state(blocked_until=NOW + timedelta(seconds=7_200.4))
    assert service(blocked, 0, NOW) == Service("daily_limit", 7_201)  # rounded up
    assert service(blocked, 0, NOW + 3 * HOUR) == Service("ok")


# ---------- what a question counts ----------
def test_groq_usage_is_the_truth_when_there_is_one():
    assert tokens_used({"prompt_tokens": 2_600, "completion_tokens": 300,
                        "total_tokens": 2_900}, groq_started=True) == 2_900
    assert tokens_used({"prompt_tokens": 2_600, "completion_tokens": 300}, True) == 2_900


def test_without_usage_only_a_started_groq_request_counts():
    assert tokens_used(None, groq_started=True) == 3_300  # timeout or error after sending
    assert tokens_used(None, groq_started=False) == 0  # timed out while queued or embedding


# ---------- Groq's daily 429 ----------
def test_only_a_long_retry_after_is_a_daily_block():
    assert daily_block_until(30, NOW) is None  # per-minute limit
    assert daily_block_until(120, NOW) is None
    assert daily_block_until(5_000, NOW) == NOW + timedelta(seconds=5_000)
