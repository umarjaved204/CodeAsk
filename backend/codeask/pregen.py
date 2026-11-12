"""Slice 5: pre-generate the suggested questions' answers (PLAN.md Q47-Q53, build step 4).

Run: python -m codeask.pregen generate pallets/itsdangerous [--max-tokens 100000]
     python -m codeask.pregen verify pallets/itsdangerous

Answers, in order, each entry of the repo's frozen `questions` list (eval/m2d_questions/
<owner>__<name>.json, Q48) that has no stored attempt yet. A replacement (Q50) is a reserve moved
into `questions` by a committed amendment, so it runs here like any other entry.

- Outside the live budget (Q53): Groq is called directly. Real usage goes into each JSON, a
  running total is printed, and the run stops before a question that could pass --max-tokens.
  Failed runs count: Groq's usage when it answered, else the API's estimate.
- Paced by the API's Pacer (Groq's headers plus our own output tokens). It waits instead of
  refusing. Each question gets the API's 90 s deadline, so a rate limit can't pass for a failure.
- No re-rolls (Q50): any answer text is the attempt, graded later, whatever it says. Only a run
  that ended in an error with no answer text is re-run, at most twice per question. Every run is
  appended to eval/results/m2d_runs_<owner>__<name>.jsonl, so the count survives restarts. A
  third error stops the run, so the cause is classified before anything else runs.
- Writes the fixture() record plus its runs to frontend/data/examples/<owner>__<name>/<id>.json,
  and the full result (raw answer, whole context, dropped chunks) to
  eval/results/m2d_raw/<owner>__<name>/<id>.json for grading and M3. The raw file never ships.

`verify` (Q51, build step 5) checks every stored answer against the real files, not the DB the
blocks came from. It makes a fresh shallow clone at the pinned SHA in a temporary folder, and
requires each shown block's content to equal the file's lines start..end exactly. The file is
decoded as ingest decodes it (strict UTF-8, BOM stripped, CRLF -> LF) and split on "\n". No
symlink is followed, and no path may leave the clone. The result (ok, SHA, time, problems) is
written into each answer's JSON as `lines_check`. No API is called and the DB isn't used.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import psycopg
import requests

from codeask import budget, config
from codeask.api.app import TrackedLLM
from codeask.ask import ask, fixture
from codeask.askqueue import Pacer
from codeask.deadline import DeadlineExceeded
from codeask.filters import decode
from codeask.llm import GroqError, RateLimited

ROOT = Path(__file__).resolve().parents[2]
MAX_ERRORS = 3  # the first run plus at most 2 re-runs (Q50)
# Ends with no answer text: re-run. Anything else is a bug and stops the run.
TRANSIENT = (GroqError, DeadlineExceeded, requests.RequestException, psycopg.Error)


class Stop(Exception):
    """Ends the run early; the message says why."""


class Paths:
    def __init__(self, slug: str, root: Path = ROOT):
        name = slug.replace("/", "__")
        self.questions = root / "eval" / "m2d_questions" / f"{name}.json"
        self.answers = root / "frontend" / "data" / "examples" / name
        self.raw = root / "eval" / "results" / "m2d_raw" / name
        self.failures = root / "eval" / "results" / "m2d_failures" / name
        self.log = root / "eval" / "results" / f"m2d_runs_{name}.jsonl"

    def stored(self, qid: str) -> bool:
        """An attempt exists: a kept answer, or one that failed grading (step 6 moves it)."""
        return (self.answers / f"{qid}.json").exists() or (self.failures / f"{qid}.json").exists()

    def runs(self, qid: str) -> list[dict]:
        if not self.log.exists():
            return []
        lines = self.log.read_text(encoding="utf-8").split("\n")
        return [r for r in (json.loads(line) for line in lines if line) if r["id"] == qid]

    def log_run(self, run: dict) -> None:
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with self.log.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(run, ensure_ascii=False) + "\n")


def load_questions(path: Path, repo: dict, pins: dict = config.FEATURED_SHAS) -> dict:
    """The frozen set, only if it is confirmed and pinned to the commit the DB holds (Q48, Q52)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    if data["repo"] != repo["slug"]:
        problems.append(f"the file is for {data['repo']}, not {repo['slug']}")
    if not data.get("confirmed"):
        problems.append("the questions are not confirmed (Q48)")
    pin = pins.get(repo["slug"])
    if not data["commit_sha"] == pin == repo["commit_sha"]:
        problems.append(f"commits differ: file {data['commit_sha'][:7]}, pin {(pin or '-')[:7]}, "
                        f"DB {repo['commit_sha'][:7]}")
    if problems:
        raise Stop("; ".join(problems))
    return data


def describe(exc: Exception) -> str:
    if isinstance(exc, psycopg.Error):  # its message names the DB host and user
        return type(exc).__name__
    return f"{type(exc).__name__}: {str(exc)[:300]}"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8",
                    newline="\n")


def wait_for(pacer: Pacer, clock, sleep) -> None:
    while True:
        now = clock()
        at = pacer.next_start(now)
        if at is None:  # nothing is running, so only limits below one question cause this
            raise Stop("Groq's limits can't fit one question (the pacer never opens)")
        if at <= now:
            return
        sleep(at - now)


def generate(pending: list[tuple[dict, list[float]]], repo: dict, paths: Paths, store, llm,
             pacer: Pacer, max_tokens: int, *, clock=time.monotonic, sleep=time.sleep,
             wall=lambda: datetime.now(timezone.utc), out=print) -> int:
    """Answers each (entry, query vector) in order; returns the tokens this run used."""
    total = 0
    for entry, vector in pending:
        qid = entry["id"]
        while True:
            errors = [r for r in paths.runs(qid) if r["outcome"] == "error"]
            if len(errors) >= MAX_ERRORS:
                raise Stop(f"{qid} ended in an error {len(errors)} times: classify the cause "
                           f"(Q50) before running it again. Tokens this run: {total:,}")
            if total + config.QUESTION_RESERVE_TOKENS > max_tokens:
                raise Stop(f"{qid} could pass --max-tokens {max_tokens:,} "
                           f"(used {total:,}, a question can take "
                           f"{config.QUESTION_RESERVE_TOKENS:,})")
            wait_for(pacer, clock, sleep)
            tracked = TrackedLLM(llm)
            pacer.start()
            try:
                result = ask(store, tracked, repo, entry["question"], vector,
                             deadline=clock() + config.ASK_DEADLINE_S)
            except TRANSIENT as exc:
                pacer.finish(clock(), config.ANSWER_MAX_TOKENS if tracked.started else 0,
                             getattr(exc, "headers", None))
                tokens = budget.tokens_used(None, tracked.started)
                total += tokens
                paths.log_run({"id": qid, "at": wall().isoformat(timespec="seconds"),
                               "outcome": "error", "tokens": tokens, "estimated": tokens > 0,
                               "error": describe(exc)})
                out(f"{qid} ERROR ({describe(exc)}); tokens this run {total:,}")
                if isinstance(exc, RateLimited) and budget.daily_block_until(exc.retry_after,
                                                                             wall()):
                    raise Stop(f"Groq's daily limit: retry after {exc.retry_after:.0f} s. "
                               f"Tokens this run: {total:,}") from exc
                continue
            now = wall()
            usage = result["usage"]
            pacer.finish(clock(), usage.get("completion_tokens", config.ANSWER_MAX_TOKENS),
                         result["headers"])
            tokens = budget.tokens_used(usage, True)
            total += tokens
            paths.log_run({"id": qid, "at": now.isoformat(timespec="seconds"),
                           "outcome": "answered", "tokens": tokens, "estimated": False,
                           "error": None})
            note = (f"{len(errors)} earlier run(s) ended in an error with no answer text and "
                    f"were re-run (Q50); see runs." if errors else None)
            record = fixture(result, repo, entry["question"], llm.model, 1, note, now)
            record["question_id"] = qid
            record["runs"] = paths.runs(qid)
            write_json(paths.answers / f"{qid}.json", record)
            write_json(paths.raw / f"{qid}.json",
                       {"question_id": qid, "question": entry["question"],
                        "generated_at": record["generated_at"], **result})
            s = result["stats"]
            out(f"{qid} {'grounded' if result['grounded'] else 'NOT GROUNDED'}: "
                f"{s['valid']} valid / {s['unverified']} unverified citations, "
                f"{tokens:,} tokens; tokens this run {total:,}")
            break
    return total


def file_lines(root: Path, rel: str) -> list[str] | None:
    """The file's lines, or None if the path is unsafe, a symlink anywhere on the way, not a
    regular file or not UTF-8. Paths are repo-relative POSIX, as the chunker stores them."""
    path = PurePosixPath(rel)
    if (not rel or "\\" in rel or path.is_absolute()
            or any(part in ("", ".", "..") for part in rel.split("/"))):
        return None
    full = root
    for part in path.parts:
        full = full / part
        if full.is_symlink():
            return None
    if not full.is_file():
        return None
    text = decode(full.read_bytes())
    return None if text is None else text.split("\n")


def check_record(record: dict, root: Path, sha: str) -> list[str]:
    """Problems with one stored answer against a checkout of `sha` at `root`; [] = ok."""
    problems = []
    if record["commit_sha"] != sha:
        problems.append(f"answer is for {record['commit_sha'][:7]}, clone is {sha[:7]}")
    for b in record["response"]["blocks"]:
        ref = f"{b['path']}:{b['start']}-{b['end']}"
        lines = file_lines(root, b["path"])
        if lines is None:
            problems.append(f"{ref}: file missing, unsafe or unreadable")
        elif not 1 <= b["start"] <= b["end"] <= len(lines):
            problems.append(f"{ref}: outside the file ({len(lines)} lines)")
        elif "\n".join(lines[b["start"] - 1:b["end"]]) != b["content"]:
            problems.append(f"{ref}: content differs from the file")
    return problems


def verify(paths: Paths, root: Path, sha: str, now: datetime) -> dict[str, list[str]]:
    """Checks every stored answer and writes the result into it; returns the problems by id."""
    results = {}
    for file in sorted(paths.answers.glob("*.json")):
        record = json.loads(file.read_text(encoding="utf-8"))
        problems = check_record(record, root, sha)
        record["lines_check"] = {"ok": not problems, "commit_sha": sha,
                                 "checked_at": now.isoformat(timespec="seconds"),
                                 "blocks": len(record["response"]["blocks"]),
                                 "problems": problems}
        write_json(file, record)
        results[file.stem] = problems
    return results


def main_verify(slug: str) -> None:
    from codeask.ingest import clone, remove_tree

    slug = slug.lower()
    pin = config.FEATURED_SHAS.get(slug)
    if pin is None:
        sys.exit(f"{slug} is not a featured repo")
    paths = Paths(slug)
    if not any(paths.answers.glob("*.json")):
        sys.exit(f"no stored answers in {paths.answers}")
    owner, name = slug.split("/")
    dest = Path(tempfile.mkdtemp(prefix="codeask-verify-")) / "repo"
    try:
        print(f"cloning {slug} at {pin[:7]} into a temporary folder ...")
        try:
            sha = clone(owner, name, pin, dest)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            sys.exit(f"git failed: {getattr(error, 'stderr', '') or error}")
        if sha != pin:
            sys.exit(f"the clone is at {sha[:7]}, not the pin {pin[:7]}")
        results = verify(paths, dest, sha, datetime.now(timezone.utc))
    finally:
        remove_tree(dest.parent)
    for qid, problems in results.items():
        print(f"{qid}: {'ok' if not problems else 'FAILED'}")
        for p in problems:
            print(f"  {p}")
    bad = sum(1 for p in results.values() if p)
    print(f"{len(results) - bad}/{len(results)} answers ok at {sha[:7]}; result written into each")
    if bad:
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("generate", help="answer the questions with no stored attempt")
    gen.add_argument("slug", help="owner/name, a featured repo")
    gen.add_argument("--max-tokens", type=int, default=config.PREGEN_MAX_TOKENS,
                     help="stop before a question that could pass this many tokens (Q53)")
    ver = commands.add_parser("verify", help="check stored answers' lines against a fresh clone")
    ver.add_argument("slug", help="owner/name, a featured repo")
    args = parser.parse_args(argv)
    if args.command == "verify":
        return main_verify(args.slug)
    if args.max_tokens <= 0:
        parser.error("--max-tokens must be positive")

    from codeask.embedder import VoyageEmbedder
    from codeask.llm import GroqClient
    from codeask.store import Store, connect

    store = Store(connect())
    repo = store.repo(args.slug.lower())
    if repo is None:
        sys.exit(f"{args.slug} is not ingested")
    paths = Paths(repo["slug"])
    try:
        data = load_questions(paths.questions, repo)
    except Stop as stop:
        sys.exit(f"refused: {stop}")
    pending = [e for e in data["questions"] if not paths.stored(e["id"])]
    if not pending:
        print(f"{repo['slug']}: every question has a stored attempt")
        return
    embedder = VoyageEmbedder()
    if repo["settings"]["space"] != embedder.space:
        sys.exit(f"{repo['slug']} was embedded in {repo['settings']['space']}, "
                 f"but the embedder is {embedder.space}")
    print(f"{repo['slug']} at {repo['commit_sha'][:7]}: answering "
          f"{', '.join(e['id'] for e in pending)} (max {args.max_tokens:,} tokens)")
    vectors = embedder.embed([e["question"] for e in pending], "query")  # one request
    try:
        total = generate(list(zip(pending, vectors)), repo, paths, store,
                         GroqClient(config.GROQ_MODEL), Pacer(), args.max_tokens)
    except Stop as stop:
        sys.exit(f"STOPPED: {stop}")
    print(f"done: {len(pending)} answered, {total:,} tokens. Next: verify, then grade.")


if __name__ == "__main__":
    main()
