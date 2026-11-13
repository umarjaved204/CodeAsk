"""The API role's grants (PLAN.md Q7, Q65, Q70, Q76): apply grants.sql, and check the role.

Neon gives roles made on the console's Roles page `neon_superuser`, which includes
pg_write_all_data (write and delete every table), so table grants would mean nothing. The API
role is therefore created with SQL, and the check is an allowlist: the role may have LOGIN and
nothing else, no memberships at all, and exactly the table privileges in EXPECTED.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg import sql

SQL_FILE = Path(__file__).with_name("grants.sql")

# What the role must hold on each table, and nothing more (grants.sql grants exactly this).
EXPECTED = {
    "repos": {"SELECT"},
    "chunks": {"SELECT"},
    "embeddings": {"SELECT"},
    "usage_settings": {"SELECT", "UPDATE"},
    "usage_hourly": {"SELECT", "INSERT", "UPDATE"},
    "usage_daily": {"SELECT", "INSERT", "UPDATE"},
}
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
ATTRIBUTES = ("rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls", "rolreplication")


def statements(schema: str, role: str) -> list[sql.Composed]:
    lines = [line for line in SQL_FILE.read_text(encoding="utf-8").split("\n")
             if line.strip() and not line.startswith("--")]
    return [sql.SQL(s.strip()).format(schema=sql.Identifier(schema), role=sql.Identifier(role))
            for s in "\n".join(lines).split(";") if s.strip()]


def role_problems(conn: psycopg.Connection, role: str) -> list[str]:
    """Empty when the role exists with no attribute besides LOGIN and no memberships."""
    row = conn.execute(sql.SQL("SELECT {} FROM pg_roles WHERE rolname = %s").format(
        sql.SQL(", ").join(map(sql.Identifier, ATTRIBUTES))), (role,)).fetchone()
    if row is None:
        return [f"role {role} does not exist"]
    problems = [f"has {name.removeprefix('rol')}" for name, on in zip(ATTRIBUTES, row) if on]
    groups = conn.execute(
        "SELECT g.rolname FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid"
        " JOIN pg_roles r ON r.oid = m.member WHERE r.rolname = %s ORDER BY 1",
        (role,)).fetchall()
    problems += [f"is a member of {g}" for (g,) in groups]
    return problems


def privilege_problems(conn: psycopg.Connection, schema: str, role: str) -> list[str]:
    """Empty when the role holds exactly EXPECTED in the schema (PUBLIC's grants count too)."""
    problems = []
    usage, create = conn.execute(
        "SELECT has_schema_privilege(%s, %s, 'USAGE'), has_schema_privilege(%s, %s, 'CREATE')",
        (role, schema, role, schema)).fetchone()
    if not usage:
        problems.append(f"no USAGE on schema {schema}")
    if create:
        problems.append(f"CREATE on schema {schema}")
    tables = {t for (t,) in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = %s", (schema,))}
    held: dict[str, set[str]] = {}
    for table, privilege in conn.execute(
            "SELECT c.relname, p FROM pg_class c"
            " JOIN pg_namespace n ON n.oid = c.relnamespace, unnest(%s::text[]) p"
            " WHERE n.nspname = %s AND c.relkind IN ('r', 'p')"
            " AND has_table_privilege(%s, c.oid, p)",
            (list(TABLE_PRIVILEGES), schema, role)):
        held.setdefault(table, set()).add(privilege)
    for table in sorted(tables | set(EXPECTED)):
        if table not in tables:
            problems.append(f"table {table} is missing")
            continue
        expected = EXPECTED.get(table, set())
        has = held.get(table, set())
        if has != expected:
            extra, missing = sorted(has - expected), sorted(expected - has)
            problems.append(f"{table}: " + "; ".join(
                part for part in (f"extra {', '.join(extra)}" if extra else "",
                                  f"missing {', '.join(missing)}" if missing else "") if part))
    return problems


def apply(conn: psycopg.Connection, schema: str, role: str) -> None:
    """Grant exactly EXPECTED, in one transaction. Refuses a role that fails the check."""
    problems = role_problems(conn, role)
    if problems:
        raise PermissionError(f"refusing to grant to {role}: " + "; ".join(problems))
    with conn.transaction():
        for statement in statements(schema, role):
            conn.execute(statement)
