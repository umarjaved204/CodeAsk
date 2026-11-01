"""Ingest a GitHub repo: clone, filter, chunk, embed what isn't cached, swap in atomically.

Run: python -m codeask.ingest https://github.com/pallets/itsdangerous [--ref <sha>]
                             [--tests] [--docs] [--yes]

The clone is separate from the logic: ingest_directory() works on any local directory with an
injected embedder, store and token counter, which is what the tests exercise.

Interruption safety: embeddings are committed after every batch, and the repo's chunk rows are
replaced in ONE transaction at the very end. Ctrl+C at any point leaves the old index live
(or no index, on a first ingest), and a re-run embeds only what's still missing.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Callable

from codeask import config
from codeask.chunker import CHUNKER_VERSION, ChunkSettings
from codeask.count import chunk_repo, eta_seconds, pack_batches, report

REPOS_DIR = Path(__file__).resolve().parents[2] / "repos"
GRAMMAR_PACKAGES = ("tree-sitter", "tree-sitter-python", "tree-sitter-javascript",
                    "tree-sitter-typescript")


def content_hash(space: str, embed_text: str) -> str:
    """The embedding cache key: exactly what is embedded, in which embedding space."""
    return hashlib.sha256(f"{space}\n{embed_text}".encode("utf-8")).hexdigest()


# ---------- the logic (no git) ----------
@dataclass
class IngestResult:
    chunks: int
    new_texts: int
    cached_texts: int
    embed_requests: int
    tokens_embedded: int
    embed_seconds: float


def settings_snapshot(chunk_settings: ChunkSettings, space: str, include_tests: bool,
                      include_docs: bool) -> dict:
    return {
        "space": space,
        "chunker_version": CHUNKER_VERSION,
        "chunker": asdict(chunk_settings),
        "grammars": {pkg: version(pkg) for pkg in GRAMMAR_PACKAGES},
        "include_tests": include_tests,
        "include_docs": include_docs,
        "filters": {"max_file_bytes": config.MAX_FILE_BYTES,
                    "max_line_chars": config.MAX_LINE_CHARS,
                    "max_avg_line_chars": config.MAX_AVG_LINE_CHARS},
    }


def ingest_directory(root: Path, slug: str, url: str, commit_sha: str, embedder, store,
                     count_tokens: Callable[[str], int], include_tests: bool = False,
                     include_docs: bool = False, settings: ChunkSettings = ChunkSettings(),
                     confirm: Callable[[str], bool] | None = None, out=print,
                     batch_tokens: int = config.BATCH_TOKENS) -> IngestResult | None:
    """Returns None if the user declines at the confirmation prompt."""
    space = embedder.space
    rc = chunk_repo(root, count_tokens, include_tests, include_docs, settings)
    out(report(slug, rc))

    rows, unique = [], {}  # unique: hash -> (embed_text, tokens), first-seen order
    for category, c in rc.chunks:
        h = content_hash(space, c.embed_text)
        unique.setdefault(h, (c.embed_text, c.token_count))
        rows.append({"path": c.path, "start_line": c.start_line, "end_line": c.end_line,
                     "kind": c.kind, "name": c.name, "breadcrumb": c.breadcrumb,
                     "category": category, "content": c.content, "content_hash": h,
                     "token_count": c.token_count})
    cached = store.existing_hashes(list(unique), space)
    missing = [h for h in unique if h not in cached]
    batches = pack_batches([unique[h][1] for h in missing], batch_tokens)
    new_tokens = sum(unique[h][1] for h in missing)
    plan = (f"to embed: {len(missing)} new texts ({new_tokens:,} tokens) in {len(batches)} "
            f"requests, ETA ~{eta_seconds(len(batches)) / 60:.1f} min; "
            f"{len(cached)} already cached")
    out(plan)
    if missing and confirm is not None and not confirm(plan):
        return None

    started = time.monotonic()
    for i, batch in enumerate(batches, 1):
        hashes = [missing[j] for j in batch]
        tokens = sum(unique[h][1] for h in hashes)
        out(f"  sending batch {i}/{len(batches)} ({len(hashes)} texts, {tokens:,} tokens; "
            f"waits for a free Voyage slot if needed) ...")
        vectors = embedder.embed([unique[h][0] for h in hashes], "document")
        store.insert_embeddings(space, [(h, unique[h][1], v) for h, v in zip(hashes, vectors)])
        out(f"  batch {i}/{len(batches)} committed at {time.monotonic() - started:.0f} s")
    embed_seconds = time.monotonic() - started

    store.swap_repo(slug, url, commit_sha,
                    settings_snapshot(settings, space, include_tests, include_docs), rows)
    return IngestResult(len(rows), len(missing), len(cached), len(batches), new_tokens,
                        embed_seconds)


# ---------- git (hardened: the URL and ref come from users) ----------
GITHUB_URL = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/"
    r"(?P<name>[A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
REF_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
GIT_TIMEOUT_S = 300


def parse_github_url(url: str) -> tuple[str, str]:
    """Only https://github.com/<owner>/<repo>: the URL goes straight into git, and file://,
    ssh: or an argument such as --upload-pack=... could make git read local files or run a
    program."""
    m = GITHUB_URL.match(url.strip())
    if not m or m["name"] in {".", ".."}:
        raise ValueError(f"not a https://github.com/<owner>/<repo> URL: {url!r}")
    return m["owner"], m["name"]


def validate_ref(ref: str) -> str:
    """A full 40-hex SHA, or a branch/tag name from a strict charset (never starting with -)."""
    if FULL_SHA.match(ref):
        return ref
    if REF_NAME.match(ref) and ".." not in ref and not ref.endswith((".lock", "/")):
        return ref
    raise ValueError(f"invalid ref: {ref!r}")


def _git(*args: str, cwd: Path, timeout: int = GIT_TIMEOUT_S) -> str:
    env = {**os.environ,
           "GIT_LFS_SKIP_SMUDGE": "1",  # never download LFS blobs
           "GIT_TERMINAL_PROMPT": "0",  # a private/missing repo fails instead of prompting
           "GIT_ALLOW_PROTOCOL": "https"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                          text=True, timeout=timeout).stdout.strip()


def remove_tree(path: Path) -> None:
    """shutil.rmtree that also deletes git's read-only object files on Windows."""
    def make_writable(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if path.exists():
        shutil.rmtree(path, onexc=make_writable)


def clone(owner: str, name: str, ref: str | None, dest: Path) -> str:
    """Fresh shallow clone of one commit; returns its SHA."""
    remove_tree(dest)
    dest.mkdir(parents=True)
    _git("init", "-q", cwd=dest)
    _git("config", "core.autocrlf", "false", cwd=dest)  # LF on disk: same hashes as Linux
    _git("remote", "add", "origin", f"https://github.com/{owner}/{name}.git", cwd=dest)
    _git("fetch", "--depth", "1", "--no-tags", "origin", ref or "HEAD", cwd=dest)
    _git("checkout", "-q", "FETCH_HEAD", cwd=dest)
    return _git("rev-parse", "HEAD", cwd=dest)


# ---------- CLI ----------
def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("url")
    parser.add_argument("--ref", help="commit SHA (40 hex) or branch/tag; default: HEAD")
    parser.add_argument("--tests", action="store_true", help="include test files")
    parser.add_argument("--docs", action="store_true", help="include docs beyond the README")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--batch-tokens", type=int, default=config.BATCH_TOKENS,
                        help=f"max tokens per Voyage request (default {config.BATCH_TOKENS})")
    args = parser.parse_args()

    try:
        owner, name = parse_github_url(args.url)
        ref = validate_ref(args.ref) if args.ref else None
    except ValueError as error:
        sys.exit(str(error))
    slug = f"{owner}/{name}".lower()

    from codeask.embedder import VoyageEmbedder
    from codeask.store import Store, connect
    from codeask.tokens import voyage_counter

    dest = REPOS_DIR / f"{owner}__{name}".lower()
    print(f"cloning {slug} ({ref or 'HEAD'}) into {dest} ...")
    try:
        sha = clone(owner, name, ref, dest)
    except subprocess.CalledProcessError as error:
        sys.exit(f"git failed: {error.stderr.strip() or error}")
    except subprocess.TimeoutExpired:
        sys.exit(f"git timed out after {GIT_TIMEOUT_S} s")
    print(f"commit {sha}")

    store = Store(connect())
    store.setup()
    embedder = VoyageEmbedder()

    def ask(plan: str) -> bool:
        return input("Proceed? [y/N] ").strip().lower() == "y"

    try:
        result = ingest_directory(dest, slug, f"https://github.com/{owner}/{name}", sha,
                                  embedder, store, voyage_counter(), args.tests, args.docs,
                                  confirm=None if args.yes else ask,
                                  batch_tokens=args.batch_tokens)
    except KeyboardInterrupt:
        sys.exit("\ninterrupted: the previous index is untouched; finished batches are cached, "
                 "so a re-run resumes from here.")
    if result is None:
        print("cancelled; nothing was embedded or changed")
        return
    minutes = result.embed_seconds / 60
    rate = f", {result.tokens_embedded / minutes:,.0f} tokens/min" if minutes > 0 else ""
    print(f"done: {result.chunks} chunks stored for {slug} @ {sha[:12]}; "
          f"{result.new_texts} new embeddings, {result.cached_texts} cached")
    print(f"voyage: {embedder.calls} requests ({embedder.rate_limited} x 429), "
          f"{result.tokens_embedded:,} tokens in {result.embed_seconds:.0f} s{rate}")


if __name__ == "__main__":
    main()
