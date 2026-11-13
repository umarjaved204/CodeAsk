"""The admin script (PLAN.md Q46 C8, step 7 amendment) against a fake store: no database."""

from datetime import datetime, timedelta, timezone

import psycopg
import pytest

import codeask.store
from codeask import admin, config

NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self, **settings):
        self.settings = {"public_budget_tokens": 120_000, "per_ip_daily": 5, "paused": False,
                         "blocked_until": None, **settings}
        self.buckets, self.writes, self.set_up = [], [], False

    def setup(self):
        self.set_up = True

    def usage(self, now):
        return {**self.settings, "buckets": self.buckets}

    def set_usage(self, **changes):
        self.writes.append(changes)
        self.settings.update(changes)


def run(store, *argv):
    return admin.run(store, admin.parser().parse_args(argv), NOW)


def test_status_shows_budget_use_limits_and_the_service():
    store = FakeStore(blocked_until=NOW + timedelta(hours=2))
    store.buckets = [(NOW, 12_345)]
    text = run(store, "status")
    assert "120,000 tokens per 24 h (used 12,345, left 107,655)" in text
    assert "5 questions per 24 h" in text and "paused         no" in text
    assert "2026-11-11T14:00:00+00:00" in text
    assert "daily_limit (try again in 7,200 s)" in text
    assert store.writes == []


@pytest.mark.parametrize("command, field, value", [
    (("pause",), "paused", True), (("resume",), "paused", False),
    (("budget", "150000"), "public_budget_tokens", 150_000),
    (("budget", "0"), "public_budget_tokens", 0),
    (("per-ip", "50"), "per_ip_daily", 50), (("per-ip", "0"), "per_ip_daily", 0),
])
def test_each_change_writes_one_field_and_prints_before_and_after(command, field, value):
    store = FakeStore(paused=not value if field == "paused" else False)
    before = store.settings[field]
    assert run(store, *command) == f"{field}: {before} -> {value}"
    assert store.writes == [{field: value}]


def test_a_budget_over_the_safe_maximum_needs_force():
    store = FakeStore()
    with pytest.raises(admin.AdminError, match="170,000"):
        run(store, "budget", str(config.PUBLIC_BUDGET_MAX_TOKENS + 1))
    assert store.writes == []
    run(store, "budget", "190000", "--force")
    assert store.settings["public_budget_tokens"] == 190_000
    run(store, "budget", str(config.PUBLIC_BUDGET_MAX_TOKENS))  # the maximum itself is fine


@pytest.mark.parametrize("command", [("budget", "-1"), ("per-ip", "-1")])
def test_negative_numbers_are_refused_and_nothing_is_written(command):
    store = FakeStore()
    with pytest.raises(admin.AdminError):
        run(store, *command)
    assert store.writes == []


def test_only_setup_creates_tables():
    store = FakeStore()
    for command in (("status",), ("pause",), ("per-ip", "9")):
        run(store, *command)
    assert not store.set_up
    assert "ready" in run(store, "setup") and store.set_up


def test_a_database_error_prints_its_type_never_the_host_or_user(monkeypatch, capsys):
    # psycopg's own message names the host and user (connect() is replaced, so no
    # DATABASE_URL is read; the pre-commit hook rightly blocks fake credential URLs).
    def refuse(env):
        raise psycopg.OperationalError("connection to server at db.secret.neon.tech user=admin")

    monkeypatch.setattr(codeask.store, "connect", refuse)
    with pytest.raises(SystemExit) as exit_:
        admin.main(["status"])
    message = str(exit_.value.code) + capsys.readouterr().out
    assert "OperationalError" in message
    assert "db.secret" not in message and "user=admin" not in message


def test_a_refused_change_exits_with_the_reason(monkeypatch):
    class Conn:
        def close(self):
            pass

    monkeypatch.setattr(codeask.store, "connect", lambda env: Conn())
    monkeypatch.setattr(codeask.store, "Store", lambda conn: FakeStore())
    with pytest.raises(SystemExit) as exit_:
        admin.main(["budget", "999999"])
    assert str(exit_.value.code).startswith("refused:")


@pytest.mark.parametrize("argv, env", [
    (["setup"], "DATABASE_OWNER_URL"),
    (["grants", "codeask_api"], "DATABASE_OWNER_URL"),
    (["grants", "codeask_api", "--check"], "DATABASE_URL"),  # read only: no owner credentials
    (["status"], "DATABASE_URL"),
    (["pause"], "DATABASE_URL"),
    (["budget", "60000"], "DATABASE_URL"),
])
def test_only_setup_and_granting_use_the_owner_url(monkeypatch, argv, env):
    used = []

    def record(name):
        used.append(name)
        raise psycopg.OperationalError("stop here")

    monkeypatch.setattr(codeask.store, "connect", record)
    with pytest.raises(SystemExit):
        admin.main(argv)
    assert used == [env]


def test_a_missing_url_names_the_variable_only(monkeypatch):
    monkeypatch.delenv("DATABASE_OWNER_URL", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)  # ignore the real .env
    with pytest.raises(SystemExit) as exit_:
        admin.main(["setup"])
    assert str(exit_.value.code) == "DATABASE_OWNER_URL is not set (see .env.example)"
