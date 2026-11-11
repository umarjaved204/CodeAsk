"""Run the public demo's limits from my machine (PLAN.md Q42, Q44, Q46 C8 and its step 7
amendment). The API reads the same row on every question, so a change applies at once, with no
redeploy (which would also wipe the per-visitor counts).

Run: python -m codeask.admin setup                 create the usage_* tables: once per database,
                                                   with a role that may create tables
     python -m codeask.admin status                budget, tokens in the last 24 h, limits
     python -m codeask.admin pause                 the kill switch: refuse new questions
     python -m codeask.admin resume
     python -m codeask.admin budget 150000         over 170,000 needs --force
     python -m codeask.admin per-ip 50             questions per visitor per 24 h

Only `setup` creates anything; the other commands work with the API's own role (Q7). Nothing
here prints DATABASE_URL: a database error shows only its type, since psycopg's messages name
the host and the user.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from codeask import budget, config


class AdminError(Exception):
    """A refused change, said plainly; nothing was written."""


def describe(state: dict, now: datetime) -> str:
    used = budget.window_tokens(state)
    limit = state["public_budget_tokens"]
    service = budget.service(state, 0, now)  # as a new visitor would find it now
    blocked = state["blocked_until"]
    lines = [
        f"budget         {limit:,} tokens per 24 h (used {used:,}, left {max(0, limit - used):,})",
        f"per visitor    {state['per_ip_daily']} questions per 24 h",
        f"paused         {'yes' if state['paused'] else 'no'}",
        f"blocked until  {blocked.isoformat(timespec='seconds') if blocked else '-'}",
        f"service now    {service.status}"
        + (f" (try again in {service.retry_after_s:,} s)" if service.retry_after_s else ""),
    ]
    return "\n".join(lines)


def change_for(args) -> dict:
    if args.command in ("pause", "resume"):
        return {"paused": args.command == "pause"}
    if args.command == "budget":
        if args.tokens < 0:
            raise AdminError("the budget can't be negative")
        if args.tokens > config.PUBLIC_BUDGET_MAX_TOKENS and not args.force:
            raise AdminError(f"{args.tokens:,} leaves less than 30,000 of Groq's 200,000 a day "
                             f"for my own use; the safe maximum is "
                             f"{config.PUBLIC_BUDGET_MAX_TOKENS:,} (add --force to go over)")
        return {"public_budget_tokens": args.tokens}
    if args.questions < 0:  # per-ip
        raise AdminError("the per-visitor number can't be negative (0 = no live questions)")
    return {"per_ip_daily": args.questions}


def run(store, args, now: datetime) -> str:
    """One command against a store; returns what to print. Pure apart from the store."""
    if args.command == "setup":
        store.setup()
        return "usage tables ready (existing settings kept)"
    if args.command == "status":
        return describe(store.usage(now), now)
    change = change_for(args)  # validated before anything is read or written
    (field,) = change
    before = store.usage(now)[field]
    store.set_usage(**change)
    after = store.usage(now)[field]
    return f"{field}: {before} -> {after}"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="create the usage_* tables (needs a role that may create)")
    sub.add_parser("status", help="show the budget, use and limits")
    sub.add_parser("pause", help="refuse new questions (the kill switch)")
    sub.add_parser("resume", help="accept questions again")
    b = sub.add_parser("budget", help="tokens per 24 h for the public demo")
    b.add_argument("tokens", type=int)
    b.add_argument("--force", action="store_true", help="allow more than the safe maximum")
    i = sub.add_parser("per-ip", help="questions per visitor per 24 h")
    i.add_argument("questions", type=int)
    return p


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    import psycopg

    from codeask.store import Store, connect

    try:
        conn = connect()
        try:
            print(run(Store(conn), args, datetime.now(timezone.utc)))
        finally:
            conn.close()
    except AdminError as exc:
        sys.exit(f"refused: {exc}")
    except psycopg.Error as exc:
        sys.exit(f"database error: {type(exc).__name__} (details withheld: they name the host)")


if __name__ == "__main__":
    main()
