"""Integration tests: real Neon (a throwaway schema per test, dropped afterwards) with the fake
embedder, so they cost no Voyage quota. Run with: pytest -m db
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from helpers import FakeEmbedder, fake_count, fake_vector

from codeask.chunker import ChunkSettings
from codeask.ingest import ingest_directory

pytestmark = pytest.mark.db
SLUG = "test/repo"
SHA_1, SHA_2 = "1" * 40, "2" * 40


@pytest.fixture(scope="module")
def conn():
    from dotenv import load_dotenv

    load_dotenv()
    if not os.environ.get("DATABASE_OWNER_URL"):  # creates schemas and ingests: the owner
        pytest.skip("DATABASE_OWNER_URL not set")
    from codeask.store import connect

    connection = connect("DATABASE_OWNER_URL")
    yield connection
    connection.close()


@pytest.fixture
def store(conn):
    from codeask.store import Store

    s = Store(conn, schema=f"codeask_test_{uuid.uuid4().hex[:8]}")
    s.setup()
    yield s
    s.drop_schema()


def function(name, last_line="    return fourth"):
    # Long enough to stay above the merge minimum, so each function is its own chunk.
    return (f"def {name}(a, b, c):\n"
            f'    """Long enough docstring to stay above the merge minimum."""\n'
            f"    first = prepare_input_values(a, b)\n"
            f"    second = combine_the_results(first, c)\n"
            f"    third = finalize_everything(second, first)\n"
            f"    fourth = validate_the_output(third, second)\n"
            f"{last_line}\n")


def write_repo(root, beta_last_line="    return fourth", extra_files=None):
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# Test repo\n\nA repo for tests.\n", encoding="utf-8")
    (root / "a.py").write_text("\n\n".join(
        [function("alpha"), function("beta", beta_last_line), function("gamma")]),
        encoding="utf-8")
    (root / "b.py").write_text(function("delta"), encoding="utf-8")
    for name, text in (extra_files or {}).items():
        (root / name).write_text(text, encoding="utf-8")
    return root


def ingest(store, root, embedder, slug=SLUG, sha=SHA_1, **kwargs):
    return ingest_directory(root, slug, f"https://github.com/{slug}", sha, embedder, store,
                            fake_count, out=lambda *a: None, **kwargs)


def embedding_count(store):
    with store.conn.transaction():
        return store.conn.execute(store._q("SELECT count(*) FROM {s}.embeddings")).fetchone()[0]


# ---------- re-runs and the cache ----------
def test_rerun_makes_zero_embedding_calls_and_no_duplicates(store, tmp_path):
    root = write_repo(tmp_path / "repo")
    first = FakeEmbedder()
    r1 = ingest(store, root, first)
    assert r1.new_texts > 0 and first.calls > 0
    assert store.chunk_count(SLUG) == r1.chunks

    second = FakeEmbedder()
    r2 = ingest(store, root, second)
    assert second.calls == 0
    assert (r2.new_texts, r2.cached_texts) == (0, r1.new_texts)
    assert store.chunk_count(SLUG) == r1.chunks  # replaced, not appended


def test_body_edit_embeds_exactly_one_new_text(store, tmp_path):
    root = write_repo(tmp_path / "repo")
    ingest(store, root, FakeEmbedder())
    write_repo(root, beta_last_line="    return fourth + 1")  # edit beta's body only

    embedder = FakeEmbedder()
    result = ingest(store, root, embedder)
    assert result.new_texts == 1
    assert len(embedder.texts) == 1 and "def beta" in embedder.texts[0]


# ---------- interruption ----------
def test_interrupted_first_ingest_resumes(store, tmp_path):
    root = write_repo(tmp_path / "repo")
    with pytest.raises(KeyboardInterrupt):
        # batch_tokens=1: one text per request, Ctrl+C during the 3rd request.
        ingest(store, root, FakeEmbedder(fail_after=2), batch_tokens=1)
    assert store.repo(SLUG) is None  # no half-built index is visible
    assert embedding_count(store) == 2  # but the finished batches were committed

    embedder = FakeEmbedder()
    result = ingest(store, root, embedder, batch_tokens=1)
    assert result.cached_texts == 2  # resumed: the 2 finished texts weren't re-embedded
    assert embedder.calls == result.new_texts
    assert store.chunk_count(SLUG) == result.chunks


def test_interrupted_reingest_keeps_old_index_live(store, tmp_path):
    root = write_repo(tmp_path / "repo")
    original = FakeEmbedder()
    r1 = ingest(store, root, original)

    with pytest.raises(KeyboardInterrupt):
        # Different settings (windows) -> different texts -> new embeddings needed.
        ingest(store, root, FakeEmbedder(fail_after=1), sha=SHA_2, batch_tokens=1,
               settings=ChunkSettings(mode="windows"))

    repo = store.repo(SLUG)
    assert repo["commit_sha"] == SHA_1
    assert repo["settings"]["chunker"]["mode"] == "ast"
    assert store.chunk_count(SLUG) == r1.chunks
    # Still searchable: a vector of an original text finds that chunk at distance ~0.
    rows = store.search(SLUG, FakeEmbedder.space, fake_vector(original.texts[0]), 1)
    assert rows and rows[0]["distance"] < 1e-5  # pgvector stores float32


# ---------- transactional swap ----------
def test_swap_rolls_back_on_error(store, tmp_path):
    root = write_repo(tmp_path / "repo")
    r1 = ingest(store, root, FakeEmbedder())
    bad_row = {"path": "x.py", "start_line": 1, "end_line": 1, "kind": "module", "name": "",
               "breadcrumb": "<module>", "category": "source", "content": None,  # NOT NULL
               "content_hash": "h", "token_count": 1}
    with pytest.raises(psycopg.Error):
        store.swap_repo(SLUG, "https://github.com/test/repo", SHA_2, {}, [bad_row])
    assert store.repo(SLUG)["commit_sha"] == SHA_1  # the repos upsert rolled back too
    assert store.chunk_count(SLUG) == r1.chunks  # and the delete of old chunks


# ---------- gc and repo deletion ----------
def test_gc_and_delete_repo_never_remove_referenced_embeddings(store, tmp_path):
    shared = {"shared.py": function("shared_helper")}
    root_a = write_repo(tmp_path / "a", extra_files=shared)
    root_b = write_repo(tmp_path / "b", extra_files=shared)
    (root_b / "b.py").write_text(function("only_in_b"), encoding="utf-8")
    ingest(store, root_a, FakeEmbedder(), slug="test/a")
    b_embedder = FakeEmbedder()
    ingest(store, root_b, b_embedder, slug="test/b")
    # b reuses a's identical files (same path + code -> same embed_text -> same hash).
    assert len(b_embedder.texts) == 1 and "only_in_b" in b_embedder.texts[0]

    # Re-ingest b after an edit: its old only_in_b text becomes an orphan.
    (root_b / "b.py").write_text(function("only_in_b", "    return 0"), encoding="utf-8")
    ingest(store, root_b, FakeEmbedder(), slug="test/b")
    before = embedding_count(store)
    assert store.gc() == 0  # orphans younger than 24 h are kept (resumable cache)
    assert store.gc(include_recent=True) == 1
    assert embedding_count(store) == before - 1

    # Deleting a: only embeddings that nothing else references go (a's delta in b.py).
    found, deleted = store.delete_repo("test/a")
    assert found and deleted == 1
    assert store.repo("test/a") is None
    rerun = FakeEmbedder()
    ingest(store, root_b, rerun, slug="test/b")
    assert rerun.calls == 0  # every embedding b uses survived
    assert store.delete_repo("test/missing") == (False, 0)


# ---------- packer metadata ----------
def test_file_chunks_lists_only_the_given_files_of_that_repo_in_line_order(store, tmp_path):
    ingest(store, write_repo(tmp_path / "a"), FakeEmbedder(), slug="test/a")
    ingest(store, write_repo(tmp_path / "b"), FakeEmbedder(), slug="test/b")
    rows = store.file_chunks("test/a", ["a.py", "missing.py"])
    assert [(r["path"], r["name"]) for r in rows] == [
        ("a.py", "alpha"), ("a.py", "beta"), ("a.py", "gamma")]
    assert [r["start_line"] for r in rows] == sorted(r["start_line"] for r in rows)
    assert set(rows[0]) == {"path", "start_line", "end_line", "kind", "name", "breadcrumb",
                            "token_count"}  # metadata only: no content, no vector


# ---------- slice 4: the usage tables (PLAN.md Q42, Q44, Q46) ----------
NOW = datetime(2026, 11, 11, 10, 30, tzinfo=timezone.utc)


def test_setup_seeds_one_settings_row_and_is_idempotent(store):
    assert store.usage(NOW) == {"public_budget_tokens": 120_000, "per_ip_daily": 5,
                                "paused": False, "blocked_until": None, "buckets": []}
    store.set_usage(per_ip_daily=100)  # the dev database's raised limit
    store.setup()  # running setup again keeps the existing row
    assert store.usage(NOW)["per_ip_daily"] == 100


def test_tokens_add_up_per_hour_and_only_the_last_24_hours_count(store):
    store.add_tokens(NOW - timedelta(hours=24), 999)  # 10:00 yesterday: outside the window
    store.add_tokens(NOW - timedelta(hours=23), 100)  # 11:00 yesterday: the oldest bucket in it
    store.add_tokens(NOW, 2_000)
    store.add_tokens(NOW.replace(minute=59), 500)  # same hour: one bucket
    buckets = store.usage(NOW)["buckets"]
    assert [tokens for _, tokens in buckets] == [100, 2_500]
    assert buckets[-1][0] == datetime(2026, 11, 11, 10, tzinfo=timezone.utc)


def test_outcomes_are_counted_per_day(store):
    for outcome in ("answered", "answered", "per_ip_limit"):
        store.count_outcome(NOW.date(), outcome)
    store.count_outcome((NOW + timedelta(days=1)).date(), "answered")
    rows = store.conn.execute(store._q(
        "SELECT day, outcome, count FROM {s}.usage_daily ORDER BY day, outcome")).fetchall()
    assert [(str(d), o, c) for d, o, c in rows] == [
        ("2026-11-11", "answered", 2), ("2026-11-11", "per_ip_limit", 1),
        ("2026-11-12", "answered", 1)]


def test_set_usage_changes_only_named_settings(store):
    until = NOW + timedelta(hours=3)
    store.set_usage(paused=True, blocked_until=until)
    state = store.usage(NOW)
    assert state["paused"] is True and state["blocked_until"] == until
    assert state["public_budget_tokens"] == 120_000
    for bad in ({"question": "x"}, {}):
        with pytest.raises(ValueError):
            store.set_usage(**bad)


def test_no_transaction_stays_open_between_store_calls(store):
    # /ask keeps one session through its queue wait (PLAN.md Q46 step 6, decision 1). On
    # Neon's pooled endpoint (PgBouncer, transaction mode) an open transaction would pin a
    # server connection for up to ~90 s; an idle one pins nothing.
    idle = psycopg.pq.TransactionStatus.IDLE
    store.usage(NOW)
    assert store.conn.info.transaction_status == idle
    store.repo(SLUG)
    assert store.conn.info.transaction_status == idle
    store.add_tokens(NOW, 10)
    store.count_outcome(NOW.date(), "answered")
    assert store.conn.info.transaction_status == idle
