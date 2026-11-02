"""M2 slice 1: compare Groq models on the same questions through the real ask() pipeline.

Run: python eval/m2_compare.py pallets/itsdangerous eval/m2_models.json

Decision rule (fixed before running, PLAN.md slice 1): the higher valid-citation rate wins,
provided its output tokens per answer allow >= 2 questions/min (1,000 output tokens/min);
ties go to qwen. Quality is judged by hand (correct / partial / wrong) in the answers file.
All questions are embedded in ONE Voyage request; models alternate, PAUSE_S apart, so each
model stays under its 8K tokens/min.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

from codeask.ask import ask
from codeask.embedder import VoyageEmbedder
from codeask.llm import GroqClient, GroqError
from codeask.store import Store, connect

MODELS = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"]
PAUSE_S = 35
OUT = Path(__file__).parent / "results"


def expected_hit(result: dict, expected: list[str]) -> bool | None:
    """At least one valid citation in an expected file (None for unanswerable questions)."""
    if not expected:
        return None
    return any(c["valid"] and c["path"] in expected for c in result["citations"])


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("slug")
    parser.add_argument("questions", type=Path)
    args = parser.parse_args()

    items = json.loads(args.questions.read_text(encoding="utf-8"))
    store = Store(connect())
    repo = store.repo(args.slug.lower())
    if repo is None:
        sys.exit(f"{args.slug} is not ingested")
    vectors = VoyageEmbedder().embed([item["question"] for item in items], "query")
    clients = {m: GroqClient(m) for m in MODELS}

    runs = []
    for i, (item, vector) in enumerate(zip(items, vectors), 1):
        for model in MODELS:
            if runs:
                time.sleep(PAUSE_S)
            print(f"Q{i} {model} ...", flush=True)
            try:
                result = ask(store, clients[model], repo, item["question"], vector)
                result["expected_hit"] = expected_hit(result, item["expected"])
            except GroqError as e:  # recorded, not fatal: one failure shouldn't lose the run
                result = {"error": str(e)}
            runs.append({"q": i, "model": model, "question": item["question"], **result})

    OUT.mkdir(exist_ok=True)
    stem = OUT / f"m2_models_{date.today()}"
    stem.with_suffix(".json").write_text(json.dumps(runs, indent=2), encoding="utf-8")

    table = ["| Q | Model | Expected file hit | Valid / cited | Parsed / attempted | Output tok | "
             "Prompt tok / context est. | LLM s | Usage extras |", "|---|---|---|---|---|---|---|---|---|"]
    answers = ["# M2 model comparison: answers to grade",
               "Grade each answer: correct / partial / wrong (unanswerable: correct = says the "
               "files don't contain it).", ""]
    for r in runs:
        if "error" in r:
            table.append(f"| {r['q']} | {r['model']} | ERROR: {r['error'][:80]} |||||||")
            continue
        s, u = r["stats"], r["usage"]
        extras = {k: v for k, v in u.items() if k not in (
            "queue_time", "prompt_tokens", "prompt_time", "completion_tokens",
            "completion_time", "total_tokens", "total_time")}
        hit = {None: "n/a", True: "yes", False: "NO"}[r["expected_hit"]]
        table.append(
            f"| {r['q']} | {r['model']} | {hit} | {s['valid']} / {s['valid'] + s['unverified']} | "
            f"{s['markers']} / {s['attempted']} | {u.get('completion_tokens')} | "
            f"{u.get('prompt_tokens')} / {r['context_estimate']} | {r['timings_s']['llm']} | "
            f"{extras or ''} reasoning chars {r['reasoning_chars']} |")
        answers += [f"## Q{r['q']} · {r['model']}", f"**{r['question']}**", "", r["answer"], "",
                    *[f"- [{c['n']}] {'ok' if c['valid'] else 'UNVERIFIED'} "
                      f"{c['path']}:{c['start']}-{c['end']}" for c in r["citations"]],
                    "", "**Grade:** ", ""]
    last = {r["model"]: r["headers"] for r in runs if "headers" in r}
    table += ["", "Last rate-limit headers per model:", *[f"- {m}: {h}" for m, h in last.items()]]
    stem.with_suffix(".md").write_text("\n".join(table) + "\n", encoding="utf-8")
    Path(f"{stem}_answers.md").write_text("\n".join(answers), encoding="utf-8")
    print("\n".join(table))
    print(f"\nWrote {stem}.md, {stem}.json and {stem}_answers.md")


if __name__ == "__main__":
    main()
