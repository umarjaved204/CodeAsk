"""Neon Postgres + pgvector storage.

Three tables:
- repos: one row per ingested repo (slug "owner/name", commit, settings snapshot).
- chunks: per repo; what the UI shows (path, lines, content) plus the content_hash.
- embeddings: shared across repos, keyed by (content_hash, space). Identical code in two repos
  shares one vector, switching models needs no re-chunking, and kept orphans make switching
  back to an earlier chunking variant free.
Plus the API's own `usage_*` tables (slice 4): the budget settings, tokens per hour and outcome
counts per day. They are the only tables the API's role may write (PLAN.md Q7, Q46).

Every statement names its schema explicitly. DATABASE_URL is Neon's pooled connection
(PgBouncer, transaction mode), which drops session settings such as search_path after each
transaction, so a SET search_path would silently stop applying.
"""

from __future__ import annotations

import os
import socket
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from codeask import config


PROD_ENV_FILE = Path(__file__).resolve().parents[2] / ".env.prod"  # gitignored, like .env


def read_env_file(path: Path) -> dict:
    from dotenv import dotenv_values

    if not path.is_file():
        raise RuntimeError(f"{path.name} not found (same names as .env.example)")
    return dotenv_values(path)


def database_url(env: str = "DATABASE_URL", prod: bool = False, read=None) -> str:
    """DATABASE_URL: the API's role, pooled. DATABASE_OWNER_URL: the owner, direct, for what
    creates, grants or writes content (admin setup and grants, ingest, gc; PLAN.md Q65).
    prod=True (an explicit --prod, Q7) reads .env.prod ONLY: a value missing there is an error,
    never dev's value from .env, and nothing from .env.prod enters the process environment."""
    if prod:
        url = (read or read_env_file)(PROD_ENV_FILE).get(env)
        if not url:
            raise RuntimeError(f"{env} is not set in .env.prod")
        return url
    from dotenv import load_dotenv

    load_dotenv()
    url = os.environ.get(env)
    if not url:
        raise RuntimeError(f"{env} is not set (see .env.example)")
    return url


def confirm_prod(url: str, action: str, ask=input) -> bool:
    """One confirmation before a write to prod, naming the host (never the URL: it holds the
    password). Typing a word, not y, so a reflex Enter can't say yes."""
    host = urlparse(url).hostname
    return ask(f"PROD database {host}\n{action}\nType prod to go ahead: ").strip() == "prod"


def connect(env: str = "DATABASE_URL", prod: bool = False) -> psycopg.Connection:
    url = database_url(env, prod)
    # Pin IPv4: from my home network libpq stalled ~30 s per IPv6 address (M0: 92 s connects).
    # hostaddr skips DNS for the socket but the hostname is still used for TLS/SNI.
    host = urlparse(url).hostname
    ipv4 = socket.getaddrinfo(host, 5432, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
    # prepare_threshold=None: PgBouncer in transaction mode can't use prepared statements.
    # autocommit=True: every `with conn.transaction()` block is then exactly one transaction.
    return psycopg.connect(url, hostaddr=ipv4, autocommit=True, prepare_threshold=None,
                           connect_timeout=30)


@contextmanager
def store_session(schema: str = "public"):
    """One connection per request (PLAN.md Q26): Neon's pooled endpoint is already a pool."""
    conn = connect()
    try:
        yield Store(conn, schema)
    finally:
        conn.close()


USAGE_SETTINGS = ("public_budget_tokens", "per_ip_daily", "paused", "blocked_until")


def hour_of(moment: datetime) -> datetime:
    """The start of the hourly bucket a moment falls in."""
    return moment.replace(minute=0, second=0, microsecond=0)


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class Store:
    def __init__(self, conn: psycopg.Connection, schema: str = "public",
                 dim: int = config.EMBED_DIM):
        self.conn, self.schema, self.dim = conn, schema, dim

    def _q(self, template: str) -> sql.Composed:
        """SQL with {s} replaced by the quoted schema name."""
        return sql.SQL(template).format(s=sql.Identifier(self.schema))

    # ---------- schema ----------
    def setup(self) -> None:
        with self.conn.transaction():
            self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            self.conn.execute(self._q("CREATE SCHEMA IF NOT EXISTS {s}"))
            self.conn.execute(self._q("""
                CREATE TABLE IF NOT EXISTS {s}.repos (
                    id bigserial PRIMARY KEY,
                    slug text NOT NULL UNIQUE,
                    url text NOT NULL,
                    commit_sha text NOT NULL,
                    settings jsonb NOT NULL,
                    ingested_at timestamptz NOT NULL DEFAULT now())"""))
            self.conn.execute(self._q("""
                CREATE TABLE IF NOT EXISTS {s}.chunks (
                    id bigserial PRIMARY KEY,
                    repo_id bigint NOT NULL REFERENCES {s}.repos(id) ON DELETE CASCADE,
                    path text NOT NULL,
                    start_line int NOT NULL,
                    end_line int NOT NULL,
                    kind text NOT NULL,
                    name text NOT NULL,
                    breadcrumb text NOT NULL,
                    category text NOT NULL,
                    content text NOT NULL,
                    content_hash text NOT NULL,
                    token_count int NOT NULL)"""))
            self.conn.execute(self._q(
                "CREATE INDEX IF NOT EXISTS chunks_repo_id ON {s}.chunks (repo_id)"))
            self.conn.execute(self._q(
                "CREATE INDEX IF NOT EXISTS chunks_content_hash ON {s}.chunks (content_hash)"))
            # No vector index: exact search is fast at this size (an index pays off at tens of
            # thousands of rows, and would make per-repo filtering approximate).
            self.conn.execute(self._q(f"""
                CREATE TABLE IF NOT EXISTS {{s}}.embeddings (
                    content_hash text NOT NULL,
                    space text NOT NULL,
                    token_count int NOT NULL,
                    vector vector({int(self.dim)}) NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (content_hash, space))"""))
            # Slice 4 (Q42, Q44, Q46): the API's own tables, the only ones it may write (Q7).
            # One settings row; tokens per hour (the rolling 24 h budget sums the last 24
            # buckets; no pruning, ~8,800 rows a year); outcome counts per day. Never question
            # text or IPs.
            self.conn.execute(self._q("""
                CREATE TABLE IF NOT EXISTS {s}.usage_settings (
                    id boolean PRIMARY KEY DEFAULT true CHECK (id),
                    public_budget_tokens int NOT NULL,
                    per_ip_daily int NOT NULL,
                    paused boolean NOT NULL DEFAULT false,
                    blocked_until timestamptz)"""))
            self.conn.execute(self._q(
                "INSERT INTO {s}.usage_settings (public_budget_tokens, per_ip_daily)"
                " VALUES (%s, %s) ON CONFLICT (id) DO NOTHING"),
                (config.PUBLIC_BUDGET_TOKENS_DEFAULT, config.PER_IP_DAILY_DEFAULT))
            self.conn.execute(self._q("""
                CREATE TABLE IF NOT EXISTS {s}.usage_hourly (
                    hour timestamptz PRIMARY KEY,
                    tokens int NOT NULL)"""))
            self.conn.execute(self._q("""
                CREATE TABLE IF NOT EXISTS {s}.usage_daily (
                    day date NOT NULL,
                    outcome text NOT NULL,
                    count int NOT NULL,
                    PRIMARY KEY (day, outcome))"""))

    def drop_schema(self) -> None:
        """Tests only: remove a throwaway schema and everything in it."""
        assert self.schema != "public"
        with self.conn.transaction():
            self.conn.execute(self._q("DROP SCHEMA IF EXISTS {s} CASCADE"))

    # ---------- embeddings ----------
    def existing_hashes(self, hashes: list[str], space: str) -> set[str]:
        with self.conn.transaction():
            rows = self.conn.execute(self._q(
                "SELECT content_hash FROM {s}.embeddings WHERE space = %s"
                " AND content_hash = ANY(%s::text[])"), (space, hashes)).fetchall()
        return {r[0] for r in rows}

    def insert_embeddings(self, space: str, rows: list[tuple[str, int, list[float]]]) -> None:
        """rows = (content_hash, token_count, vector). Committed immediately, so an
        interrupted ingest keeps every finished batch as cache."""
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.executemany(self._q(
                "INSERT INTO {s}.embeddings (content_hash, space, token_count, vector)"
                " VALUES (%s, %s, %s, %s::vector) ON CONFLICT DO NOTHING"),
                [(h, space, n, vector_literal(v)) for h, n, v in rows])

    # ---------- repos and chunks ----------
    def swap_repo(self, slug: str, url: str, commit_sha: str, settings: dict,
                  chunks: list[dict]) -> int:
        """Replace a repo's chunk set in ONE transaction: readers see the old index or the new
        one, never a mix. On any error everything rolls back."""
        with self.conn.transaction(), self.conn.cursor() as cur:
            repo_id = cur.execute(self._q("""
                INSERT INTO {s}.repos (slug, url, commit_sha, settings)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET url = EXCLUDED.url,
                    commit_sha = EXCLUDED.commit_sha, settings = EXCLUDED.settings,
                    ingested_at = now()
                RETURNING id"""), (slug, url, commit_sha, Jsonb(settings))).fetchone()[0]
            cur.execute(self._q("DELETE FROM {s}.chunks WHERE repo_id = %s"), (repo_id,))
            cur.executemany(self._q("""
                INSERT INTO {s}.chunks (repo_id, path, start_line, end_line, kind, name,
                    breadcrumb, category, content, content_hash, token_count)
                VALUES (%(repo_id)s, %(path)s, %(start_line)s, %(end_line)s, %(kind)s,
                    %(name)s, %(breadcrumb)s, %(category)s, %(content)s, %(content_hash)s,
                    %(token_count)s)"""), [{**c, "repo_id": repo_id} for c in chunks])
        return repo_id

    def repo(self, slug: str) -> dict | None:
        with self.conn.transaction():
            row = self.conn.execute(self._q(
                "SELECT id, slug, url, commit_sha, settings, ingested_at FROM {s}.repos"
                " WHERE slug = %s"), (slug,)).fetchone()
        if row is None:
            return None
        return dict(zip(("id", "slug", "url", "commit_sha", "settings", "ingested_at"), row))

    # ---------- usage (slice 4: Q42, Q44, Q46) ----------
    def usage(self, now: datetime) -> dict:
        """The settings row plus the token buckets of the last 24 hours (the current hour and the
        23 before it), read in one transaction. Raises if the settings row is missing."""
        since = hour_of(now) - timedelta(hours=23)
        with self.conn.transaction():
            row = self.conn.execute(self._q(
                "SELECT public_budget_tokens, per_ip_daily, paused, blocked_until"
                " FROM {s}.usage_settings")).fetchone()
            buckets = self.conn.execute(self._q(
                "SELECT hour, tokens FROM {s}.usage_hourly WHERE hour >= %s ORDER BY hour"),
                (since,)).fetchall()
        if row is None:
            raise LookupError("usage_settings has no row (run Store.setup)")
        return {**dict(zip(USAGE_SETTINGS, row)), "buckets": [(h, t) for h, t in buckets]}

    def add_tokens(self, now: datetime, tokens: int) -> None:
        """Add an answer's real token use to the current hour's bucket."""
        with self.conn.transaction():
            self.conn.execute(self._q("""
                INSERT INTO {s}.usage_hourly (hour, tokens) VALUES (%s, %s)
                ON CONFLICT (hour) DO UPDATE SET tokens = {s}.usage_hourly.tokens + EXCLUDED.tokens
            """), (hour_of(now), tokens))

    def count_outcome(self, day: date, outcome: str) -> None:
        with self.conn.transaction():
            self.conn.execute(self._q("""
                INSERT INTO {s}.usage_daily (day, outcome, count) VALUES (%s, %s, 1)
                ON CONFLICT (day, outcome) DO UPDATE SET count = {s}.usage_daily.count + 1
            """), (day, outcome))

    def set_usage(self, **changes) -> None:
        """Update settings fields by name (the admin script, and `blocked_until` from the API)."""
        unknown = set(changes) - set(USAGE_SETTINGS)
        if unknown or not changes:
            raise ValueError(f"unknown or no usage settings: {sorted(unknown)}")
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(name)) for name in changes)
        with self.conn.transaction():
            self.conn.execute(
                sql.SQL("UPDATE {s}.usage_settings SET {a}").format(
                    s=sql.Identifier(self.schema), a=assignments),
                list(changes.values()))

    def chunk_count(self, slug: str) -> int:
        with self.conn.transaction():
            return self.conn.execute(self._q(
                "SELECT count(*) FROM {s}.chunks c JOIN {s}.repos r ON r.id = c.repo_id"
                " WHERE r.slug = %s"), (slug,)).fetchone()[0]

    def search(self, slug: str, space: str, vector: list[float], k: int = 5) -> list[dict]:
        """Exact cosine search over one repo's chunks."""
        with self.conn.transaction():
            rows = self.conn.execute(self._q("""
                SELECT c.path, c.start_line, c.end_line, c.kind, c.breadcrumb, c.content,
                       c.token_count, e.vector <=> %s::vector AS distance
                FROM {s}.chunks c
                JOIN {s}.repos r ON r.id = c.repo_id
                JOIN {s}.embeddings e ON e.content_hash = c.content_hash AND e.space = %s
                WHERE r.slug = %s
                ORDER BY distance
                LIMIT %s"""), (vector_literal(vector), space, slug, k)).fetchall()
        keys = ("path", "start_line", "end_line", "kind", "breadcrumb", "content", "token_count",
                "distance")
        return [dict(zip(keys, row)) for row in rows]

    def file_chunks(self, slug: str, paths: list[str]) -> list[dict]:
        """Metadata of every chunk in these files (no content, no vectors), in file and line
        order. The packer uses it to see which lines between two retrieved chunks belong to
        no chunk (blank, so the two can merge) and to list a class's members."""
        with self.conn.transaction():
            rows = self.conn.execute(self._q("""
                SELECT c.path, c.start_line, c.end_line, c.kind, c.name, c.breadcrumb,
                       c.token_count
                FROM {s}.chunks c
                JOIN {s}.repos r ON r.id = c.repo_id
                WHERE r.slug = %s AND c.path = ANY(%s::text[])
                ORDER BY c.path, c.start_line"""), (slug, paths)).fetchall()
        keys = ("path", "start_line", "end_line", "kind", "name", "breadcrumb", "token_count")
        return [dict(zip(keys, row)) for row in rows]

    # ---------- cleanup ----------
    def gc(self, include_recent: bool = False, recent_hours: int = 24) -> int:
        """Delete embeddings no chunk references. Recent ones are kept by default: they may
        belong to an interrupted ingest that a re-run will resume from."""
        age = sql.SQL("") if include_recent else sql.SQL(
            "AND e.created_at < now() - make_interval(hours => {})").format(
            sql.Literal(int(recent_hours)))
        with self.conn.transaction():
            cur = self.conn.execute(sql.SQL("""
                DELETE FROM {s}.embeddings e
                WHERE NOT EXISTS (SELECT 1 FROM {s}.chunks c
                                  WHERE c.content_hash = e.content_hash) {age}""").format(
                s=sql.Identifier(self.schema), age=age))
            return cur.rowcount

    def delete_repo(self, slug: str) -> tuple[bool, int]:
        """Delete a repo and its chunks, then only the embeddings that were referenced by
        that repo and nothing else (never another ingest's resumable cache)."""
        with self.conn.transaction():
            row = self.conn.execute(self._q("SELECT id FROM {s}.repos WHERE slug = %s"),
                                    (slug,)).fetchone()
            if row is None:
                return False, 0
            hashes = [r[0] for r in self.conn.execute(self._q(
                "SELECT DISTINCT content_hash FROM {s}.chunks WHERE repo_id = %s"),
                (row[0],)).fetchall()]
            self.conn.execute(self._q("DELETE FROM {s}.repos WHERE id = %s"), (row[0],))
            cur = self.conn.execute(self._q("""
                DELETE FROM {s}.embeddings e
                WHERE e.content_hash = ANY(%s::text[])
                  AND NOT EXISTS (SELECT 1 FROM {s}.chunks c
                                  WHERE c.content_hash = e.content_hash)"""), (hashes,))
            return True, cur.rowcount
