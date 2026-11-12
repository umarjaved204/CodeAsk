"""Slice 5: pre-generate the suggested questions' answers (PLAN.md Q47-Q53, build step 4).

Run: python -m codeask.pregen generate pallets/itsdangerous [--max-tokens 100000]
     python -m codeask.pregen verify pallets/itsdangerous
     python -m codeask.pregen export pallets/itsdangerous

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

`export` (build step 7) writes frontend/data/examples/<owner>__<name>/index.json. The index
holds the passing answers' ids and questions, flagship first and the rest in question order.
It also writes two generated modules (step 8, D1):
- the repo's set.ts, which imports its index and answers;
- frontend/data/examples/sets.ts, one loader per exported repo, regenerated from every folder
  that has an index.json.

Export writes nothing if any of these hold:
- the pins disagree (config, featured.json, the dev DB);
- an answer is for another commit;
- an answer has no grade, or a grade with an unknown value;
- an answer's lines check isn't ok;
- a stored question differs from the frozen one;
- no answer passes.

An answer that doesn't pass (Q50) is left out and reported; step 6 moves it to failures. Pass
and flagship are computed from the grade's typed fields, never stored.
"""

from __future__ import annotations

import argparse
import json
import re
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
INDEX = "index.json"  # the per-repo order the frontend reads (Q47); every other file is an answer
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

    def answer_files(self) -> list[Path]:
        return sorted(f for f in self.answers.glob("*.json") if f.name != INDEX)

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
    for file in paths.answer_files():
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
    if not paths.answer_files():
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


# ---------- export (build step 7, Q47, Q48, Q50, Q52) ----------
# A grade's typed fields and their allowed values. Pass and flagship are computed from them,
# never stored, so no field can contradict another (Q37).
GRADE_VALUES = {
    "correct": {"correct", "incomplete", "incorrect"},
    "grounded": {"yes", "no"},
    "unsupported": {"none", "minor", "load-bearing"},
    "omission": {"none", "minor", "material"},
    "reviewer": {"claude", "author"},
}
FLAGSHIP_MIN_CITATIONS = 3


def grade_problems(record: dict) -> list[str]:
    grade = record.get("grade")
    if not grade:
        return ["no grade"]
    return [f"grade.{k} is {grade.get(k)!r}, not one of {sorted(v)}"
            for k, v in GRADE_VALUES.items() if grade.get(k) not in v]


def valid_citations(record: dict) -> int:
    return sum(1 for c in record["response"]["citations"] if c["valid"])


def passes(record: dict) -> bool:
    """Q50 (with the unsupported-claims amendment): grounded, every citation valid, no
    incorrect claim, no load-bearing unsupported claim, and the cited lines checked."""
    g, citations = record["grade"], record["response"]["citations"]
    return (g["grounded"] == "yes" and g["correct"] != "incorrect"
            and g["unsupported"] != "load-bearing" and record["response"]["grounded"]
            and bool(citations) and all(c["valid"] for c in citations)
            and record.get("lines_check", {}).get("ok") is True)


def truncated(record: dict) -> bool:
    """Hit the output cap: that is when Groq stops with finish_reason "length"."""
    return (record.get("usage") or {}).get("completion_tokens", 0) >= config.ANSWER_MAX_TOKENS


def flagship_misses(record: dict) -> list[str]:
    """Why a passing answer can't lead its repo (Q48); [] = it can."""
    g, misses = record["grade"], []
    if g["correct"] != "correct":
        misses.append(f"graded {g['correct']}")
    if g["omission"] == "material":
        misses.append("a material omission")
    if valid_citations(record) < FLAGSHIP_MIN_CITATIONS:
        misses.append(f"{valid_citations(record)} valid citations")
    if truncated(record):
        misses.append("truncated")
    return misses


def build_index(data: dict, records: dict[str, dict], pins: list[str],
                now: datetime) -> tuple[dict, list[str]]:
    """The repo's index.json and what was left out, or Stop if anything must be fixed first.
    `records` maps question id -> stored answer; `pins` are the SHAs that must all agree
    (config, featured.json, the dev DB)."""
    sha = data["commit_sha"]
    problems = [f"pins differ: {sorted({p[:7] for p in pins + [sha]})}"] \
        if any(p != sha for p in pins) else []
    for qid, record in records.items():
        if record["commit_sha"] != sha:
            problems.append(f"{qid}: answer is for {record['commit_sha'][:7]}, pin {sha[:7]}")
        if record.get("question_id") not in (None, qid):
            problems.append(f"{qid}: the file says it answers {record['question_id']}")
        if not (record.get("lines_check") or {}).get("ok"):
            problems.append(f"{qid}: lines_check is not ok (run verify)")
        problems += [f"{qid}: {p}" for p in grade_problems(record)]
    if problems:
        raise Stop("; ".join(problems))

    order = [e for e in data["questions"] if e["id"] in records]
    left_out = [f"{e['id']}: not generated yet" for e in data["questions"]
                if e["id"] not in records]
    passed = []
    for e in order:
        if records[e["id"]]["question"] != e["question"]:
            raise Stop(f"{e['id']}: the stored question differs from the frozen one (Q48)")
        if passes(records[e["id"]]):
            passed.append(e)
        else:
            left_out.append(f"{e['id']}: does not pass (Q50); step 6 moves it to failures")
    if not passed:
        raise Stop("no passing answer to export")
    lead = next((e for e in passed if not flagship_misses(records[e["id"]])), None)
    note = None
    if lead is None:
        lead = passed[0]
        note = (f"no passing answer meets the flagship rule (Q48); {lead['id']} leads as the "
                f"first passing: {', '.join(flagship_misses(records[lead['id']]))}")
    ordered = [lead] + [e for e in passed if e is not lead]
    index = {"repo": data["repo"], "commit_sha": sha,
             "exported_at": now.isoformat(timespec="seconds"),
             "flagship": lead["id"], "flagship_note": note,
             "questions": [{"id": e["id"], "question": e["question"]} for e in ordered]}
    return index, left_out


EXAMPLES = ROOT / "frontend" / "data" / "examples"
SETS = "sets.ts"
GENERATED = ("// GENERATED by `python -m codeask.pregen export`. Do not edit: re-run export.\n"
             "/* eslint-disable */\n")


def render_set(index: dict) -> str:
    """<owner>__<name>/set.ts: the repo's index and answers as one module, so the bundler
    makes one chunk per repo (PLAN.md step 8, D1)."""
    ids = [q["id"] for q in index["questions"]]
    bad = [i for i in ids if not re.fullmatch(r"[a-z][a-z0-9_]*", i)]
    if bad:
        raise Stop(f"ids that can't be import names: {bad}")
    return (GENERATED + 'import index from "./index.json";\n'
            + "".join(f'import {i} from "./{i}.json";\n' for i in ids)
            + f"\nexport default {{ index, answers: {{ {', '.join(ids)} }} }};\n")


def exported_slugs(examples: Path = EXAMPLES) -> list[str]:
    """Repos with an index.json, sorted: the stable order of sets.ts."""
    return sorted(json.loads((d / INDEX).read_text(encoding="utf-8"))["repo"]
                  for d in examples.iterdir() if (d / INDEX).is_file())


def render_sets(slugs: list[str]) -> str:
    """sets.ts: one dynamic loader per exported repo; a repo not listed has no stored set."""
    lines = "".join(f'  "{s}": () => import("./{s.replace("/", "__")}/set"),\n' for s in slugs)
    return (GENERATED + "// One loader per exported repo, each its own chunk (PLAN.md slice 5, "
            "step 8, D1).\n"
            "export const LOADERS: Record<string, () => Promise<{ default: unknown }>> = {\n"
            + lines + "};\n")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def main_export(slug: str) -> None:
    from codeask.store import Store, connect

    store = Store(connect())
    repo = store.repo(slug.lower())
    if repo is None:
        sys.exit(f"{slug} is not ingested")
    paths = Paths(repo["slug"])
    featured = json.loads((ROOT / "frontend" / "data" / "featured.json")
                          .read_text(encoding="utf-8"))
    listed = {f["slug"]: f["commit_sha"] for f in featured}
    try:
        data = load_questions(paths.questions, repo)
        if repo["slug"] not in listed:
            raise Stop(f"{repo['slug']} is not in featured.json")
        records = {f.stem: json.loads(f.read_text(encoding="utf-8"))
                   for f in paths.answer_files()}
        unknown = sorted(set(records) - {e["id"] for e in data["questions"]})
        if unknown:
            raise Stop(f"answers for ids not in `questions`: {', '.join(unknown)}")
        index, left_out = build_index(data, records, [listed[repo["slug"]], repo["commit_sha"]],
                                      datetime.now(timezone.utc))
        module = render_set(index)
    except Stop as stop:
        sys.exit(f"refused, nothing written: {stop}")
    write_json(paths.answers / INDEX, index)
    write_text(paths.answers / "set.ts", module)
    write_text(EXAMPLES / SETS, render_sets(exported_slugs()))
    for line in left_out:
        print(f"left out {line}")
    if index["flagship_note"]:
        print(f"NOTE: {index['flagship_note']}")
    print(f"wrote {paths.answers / INDEX}: {len(index['questions'])} answers, "
          f"flagship {index['flagship']}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("generate", help="answer the questions with no stored attempt")
    gen.add_argument("slug", help="owner/name, a featured repo")
    gen.add_argument("--max-tokens", type=int, default=config.PREGEN_MAX_TOKENS,
                     help="stop before a question that could pass this many tokens (Q53)")
    ver = commands.add_parser("verify", help="check stored answers' lines against a fresh clone")
    ver.add_argument("slug", help="owner/name, a featured repo")
    exp = commands.add_parser("export", help="write index.json from the passing answers")
    exp.add_argument("slug", help="owner/name, a featured repo")
    args = parser.parse_args(argv)
    if args.command == "verify":
        return main_verify(args.slug)
    if args.command == "export":
        return main_export(args.slug)
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
