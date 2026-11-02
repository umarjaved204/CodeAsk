"""M2 slice 2: save the top-K retrieval candidates for the comparison questions.

Run: python eval/m2_candidates.py pallets/itsdangerous eval/m2_models.json
     python eval/m2_candidates.py --add-file-chunks eval/results/m2_candidates_<date>.json

All questions are embedded in ONE Voyage request. The query vectors are saved too, so later
steps (a larger K, file_chunks) re-query the DB without another Voyage call. The packer
variants (PLAN.md Q20) and the Q5 regression test then run offline from this file.
--add-file-chunks adds the metadata of every chunk in the candidate files (DB only, no Voyage).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from codeask.embedder import VoyageEmbedder
from codeask.store import Store, connect

K = 15
OUT = Path(__file__).parent / "results"


def add_file_chunks(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    paths = sorted({r["path"] for q in data["questions"] for r in q["candidates"]})
    rows = Store(connect()).file_chunks(data["repo"], paths)
    data["file_chunks"] = rows
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"added {len(rows)} chunk rows from {len(paths)} files to {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--add-file-chunks", type=Path, metavar="CANDIDATES_JSON")
    parser.add_argument("slug", nargs="?")
    parser.add_argument("questions", type=Path, nargs="?")
    args = parser.parse_args()
    if args.add_file_chunks:
        return add_file_chunks(args.add_file_chunks)
    if not args.slug or not args.questions:
        parser.error("give SLUG QUESTIONS, or --add-file-chunks CANDIDATES_JSON")

    items = json.loads(args.questions.read_text(encoding="utf-8"))
    store = Store(connect())
    repo = store.repo(args.slug.lower())
    if repo is None:
        sys.exit(f"{args.slug} is not ingested")
    embedder = VoyageEmbedder()
    space = repo["settings"]["space"]
    if space != embedder.space:
        sys.exit(f"{args.slug} was embedded in {space}, but the embedder is {embedder.space}")
    vectors = embedder.embed([item["question"] for item in items], "query")

    questions = []
    for i, (item, vector) in enumerate(zip(items, vectors), 1):
        rows = store.search(repo["slug"], space, vector, K)
        questions.append({"q": i, **item, "vector": vector, "candidates": rows})
        print(f"Q{i} {item['question']}")
        for rank, row in enumerate(rows, 1):
            print(f"  {rank:>2}. {row['distance']:.3f} {row['token_count']:>4} tok  "
                  f"{row['kind']:<12} {row['path']}:{row['start_line']}-{row['end_line']}  "
                  f"{row['breadcrumb']}")

    OUT.mkdir(exist_ok=True)
    out = OUT / f"m2_candidates_{date.today()}.json"
    out.write_text(json.dumps({
        "repo": repo["slug"], "commit_sha": repo["commit_sha"], "settings": repo["settings"],
        "k": K, "questions": questions}, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
