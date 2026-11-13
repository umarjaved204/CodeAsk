"""The API role's grants against real Neon (PLAN.md Q70 part 1, Q76): a throwaway schema and
uniquely named test roles in the dev project, all dropped afterwards. Needs DATABASE_OWNER_URL
(the owner, direct: SET ROLE and the session-level role below need a real session, which the
pooled endpoint doesn't keep). Run with: pytest -m db

The test roles act through SET ROLE, so they need no password. Database-level privileges
(CREATE on the database) are outside a schema test: the rolled-back prod check covers them.
"""

import os
import re
import uuid
from contextlib import contextmanager

import psycopg
import pytest
from helpers import fake_vector
from psycopg import sql
from test_api import SALT, FakeLLM, OpenPacer

from codeask import grants
from codeask.askqueue import AskQueue

pytestmark = pytest.mark.db

PREFIX = "codeask_grants_test_"
TEST_ROLE = re.compile(r"^codeask_grants_test_[0-9a-f]{8}(_group)?$")
NEVER_DROP = {"codeask_api"}  # the real API role, whatever the pattern says
SLUG, SPACE, SHA = "test/grants", "fake:1024:document", "3" * 40
VECTOR = fake_vector("the one chunk")
CHUNK = {"path": "signer.py", "start_line": 1, "end_line": 5, "kind": "function", "name": "f",
         "breadcrumb": "f", "category": "source", "content_hash": "h1", "token_count": 10,
         "content": "\n".join(f"line {i}" for i in range(1, 6))}


def ident(name):
    return sql.Identifier(name)


def drop_role(conn, role):
    """The only way these tests drop a role: test-prefixed names only, never codeask_api."""
    if not TEST_ROLE.match(role) or role in NEVER_DROP:
        raise AssertionError(f"refusing to drop {role}")
    conn.execute(sql.SQL("DROP OWNED BY {}").format(ident(role)))
    conn.execute(sql.SQL("DROP ROLE {}").format(ident(role)))


def create_role(conn, suffix="", attributes=""):
    role = f"{PREFIX}{uuid.uuid4().hex[:8]}{suffix}"
    conn.execute(sql.SQL(f"CREATE ROLE {{}} NOLOGIN {attributes}").format(ident(role)))
    # SET ROLE and DROP OWNED BY need the owner to hold the role (Postgres 16+ gives a role's
    # creator ADMIN only, without SET).
    conn.execute(sql.SQL("GRANT {} TO CURRENT_USER WITH SET TRUE").format(ident(role)))
    return role


@pytest.fixture(scope="module")
def owner():
    from dotenv import load_dotenv

    load_dotenv()
    if not os.environ.get("DATABASE_OWNER_URL"):
        pytest.skip("DATABASE_OWNER_URL not set")
    from codeask.store import connect

    conn = connect("DATABASE_OWNER_URL")
    stale = conn.execute("SELECT rolname FROM pg_roles WHERE starts_with(rolname, %s)",
                         (PREFIX,)).fetchall()
    for (role,) in stale:  # left by a crashed run
        if TEST_ROLE.match(role):
            drop_role(conn, role)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def granted(owner):
    """A throwaway schema with one ingested chunk, and a role holding exactly the grants.
    Teardown order: the schema, then DROP OWNED BY, then DROP ROLE."""
    from codeask.store import Store

    role = create_role(owner)
    store = Store(owner, f"codeask_test_{uuid.uuid4().hex[:8]}")
    try:
        store.setup()
        store.insert_embeddings(SPACE, [("h1", 10, VECTOR)])
        store.swap_repo(SLUG, f"https://github.com/{SLUG}", SHA, {"space": SPACE}, [CHUNK])
        grants.apply(owner, store.schema, role)
        yield store.schema, role
    finally:
        store.drop_schema()
        drop_role(owner, role)


@pytest.fixture
def new_role(owner):
    made = []

    def make(suffix="", attributes=""):
        made.append(create_role(owner, suffix, attributes))
        return made[-1]

    yield make
    for role in reversed(made):
        drop_role(owner, role)


def as_role(conn, role, statement):
    """One attempt in its own transaction, always rolled back."""
    with conn.transaction(force_rollback=True):
        conn.execute(sql.SQL("SET LOCAL ROLE {}").format(ident(role)))
        conn.execute(statement)


# ---------- negative: everything outside the grants is refused ----------
NOT_ALLOWED = [
    "INSERT INTO {s}.repos (slug, url, commit_sha, settings)"
    " VALUES ('x/y', 'u', 'c', jsonb_build_object())",
    "UPDATE {s}.repos SET url = url",
    "DELETE FROM {s}.repos",
    "INSERT INTO {s}.chunks SELECT * FROM {s}.chunks",
    "UPDATE {s}.chunks SET content = content",
    "DELETE FROM {s}.chunks",
    "INSERT INTO {s}.embeddings SELECT * FROM {s}.embeddings",
    "UPDATE {s}.embeddings SET token_count = token_count",
    "DELETE FROM {s}.embeddings",
    "TRUNCATE {s}.repos CASCADE",
    "TRUNCATE {s}.chunks",
    "TRUNCATE {s}.embeddings",
    "INSERT INTO {s}.usage_settings (id, public_budget_tokens, per_ip_daily)"
    " VALUES (true, 1, 1)",
    "DELETE FROM {s}.usage_settings",
    "DELETE FROM {s}.usage_hourly",
    "DELETE FROM {s}.usage_daily",
    "TRUNCATE {s}.usage_settings",
    "TRUNCATE {s}.usage_hourly",
    "TRUNCATE {s}.usage_daily",
    "CREATE TABLE {s}.intruder (x int)",
    "CREATE INDEX intruder ON {s}.chunks (path)",
    "ALTER TABLE {s}.usage_settings ADD COLUMN x int",
    "DROP TABLE {s}.usage_daily",
]


@pytest.mark.parametrize("template", NOT_ALLOWED)
def test_the_api_role_is_refused_everything_outside_its_grants(owner, granted, template):
    schema, role = granted
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_role(owner, role, sql.SQL(template).format(s=ident(schema)))


# ---------- the check (the same one `admin grants --check` runs) ----------
def test_the_check_passes_after_the_grants(owner, granted):
    schema, role = granted
    assert grants.role_problems(owner, role) == []
    assert grants.privilege_problems(owner, schema, role) == []


def test_the_check_catches_a_privilege_added_later(owner, granted):
    schema, role = granted
    with owner.transaction(force_rollback=True):
        owner.execute(sql.SQL("GRANT DELETE ON {}.chunks TO {}").format(ident(schema), ident(role)))
        assert grants.privilege_problems(owner, schema, role) == ["chunks: extra DELETE"]


def test_a_role_with_an_attribute_is_refused_and_gets_nothing(owner, granted, new_role):
    schema, _ = granted
    role = new_role(attributes="CREATEDB")
    assert grants.role_problems(owner, role) == ["has createdb"]
    with pytest.raises(PermissionError, match="has createdb"):
        grants.apply(owner, schema, role)
    assert not owner.execute("SELECT has_schema_privilege(%s, %s, 'USAGE')",
                             (role, schema)).fetchone()[0]


def test_a_role_with_any_membership_is_refused(owner, granted, new_role):
    # A stand-in group role: neon_superuser and pg_write_all_data are memberships too.
    schema, _ = granted
    group, role = new_role("_group"), new_role()
    owner.execute(sql.SQL("GRANT {} TO {}").format(ident(group), ident(role)))
    assert grants.role_problems(owner, role) == [f"is a member of {group}"]
    with pytest.raises(PermissionError, match="is a member of"):
        grants.apply(owner, schema, role)


def test_a_missing_role_is_reported(owner):
    assert grants.role_problems(owner, f"{PREFIX}00000000") == [
        f"role {PREFIX}00000000 does not exist"]


# ---------- positive: the real app works as the API role ----------
class QueryEmbedder:
    space = SPACE

    def embed(self, texts, input_type, deadline=None):
        return [VECTOR for _ in texts]  # the chunk's own vector: it is the top result


def test_the_app_answers_and_counts_as_the_api_role(owner, granted, monkeypatch):
    from codeask.api.app import create_app
    from codeask.store import Store, connect

    schema, role = granted
    assert "-pooler" not in owner.info.host, \
        "DATABASE_OWNER_URL must be the DIRECT URL: the pooler drops a session-level SET ROLE"

    @contextmanager
    def session():
        """One connection per request, as store_session gives the real app; each acts as
        the role for its whole session (direct URL), checked before use."""
        conn = connect("DATABASE_OWNER_URL")
        try:
            conn.execute(sql.SQL("SET ROLE {}").format(ident(role)))
            assert conn.execute("SELECT current_user").fetchone()[0] == role
            yield Store(conn, schema)
        finally:
            conn.close()

    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    from fastapi.testclient import TestClient

    app = create_app(session, QueryEmbedder(), FakeLLM(), featured=(SLUG,), ip_salt=SALT,
                     queue=AskQueue(OpenPacer()))
    with TestClient(app) as c:
        assert c.get("/status").json()["service"] == "ok"
        assert [r["slug"] for r in c.get("/repos").json()] == [SLUG]
        r = c.post("/ask", json={"repo": SLUG, "question": "How is it signed?"},
                   headers={"CF-Connecting-IP": "203.0.113.9"})
    assert r.status_code == 200
    assert r.json()["grounded"]
    with session() as store:
        store.set_usage(paused=True)  # the kill switch, as the role
    s = ident(schema)
    assert owner.execute(sql.SQL("SELECT sum(tokens) FROM {}.usage_hourly").format(s)
                         ).fetchone()[0] == 3_000
    assert owner.execute(sql.SQL("SELECT count FROM {}.usage_daily WHERE outcome = 'answered'")
                         .format(s)).fetchone()[0] == 1
    assert owner.execute(sql.SQL("SELECT paused FROM {}.usage_settings").format(s)
                         ).fetchone()[0] is True
