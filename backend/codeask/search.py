"""Retrieve the top chunks for a question (no LLM). Proves an ingest actually retrieves.

Run: python -m codeask.search pallets/itsdangerous "How is the signing key derived?"
     python -m codeask.search pallets/itsdangerous --sanity eval/sanity/itsdangerous.json

--sanity embeds all its questions in ONE Voyage request (several texts per call is how we
live with 3 requests/min) and prints the rank of the first expected file for each.
This is a regression check, not the M3 eval.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def first_rank(rows: list[dict], expected: list[str]) -> int | None:
    """1-based rank of the first chunk from an expected file."""
    return next((i for i, row in enumerate(rows, 1) if row["path"] in expected), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("slug", help="owner/name, as ingested")
    parser.add_argument("question", nargs="?")
    parser.add_argument("--sanity", type=Path, help="JSON file of {question, expected}")
    parser.add_argument("-k", type=int, default=5)
    args = parser.parse_args()
    if not args.question and not args.sanity:
        parser.error("give a question or --sanity FILE")

    from codeask.embedder import VoyageEmbedder
    from codeask.store import Store, connect

    store = Store(connect())
    repo = store.repo(args.slug.lower())
    if repo is None:
        sys.exit(f"{args.slug} is not ingested")
    embedder = VoyageEmbedder()
    space = repo["settings"]["space"]
    if space != embedder.space:
        sys.exit(f"{args.slug} was embedded in {space}, but the embedder is {embedder.space}")

    if args.question:
        (vector,) = embedder.embed([args.question], "query")
        for i, row in enumerate(store.search(repo["slug"], space, vector, args.k), 1):
            print(f"{i}. {row['distance']:.3f}  {row['kind']:<12} {row['breadcrumb']}\n"
                  f"   {row['path']}:{row['start_line']}-{row['end_line']}")
        return

    items = json.loads(args.sanity.read_text(encoding="utf-8"))
    vectors = embedder.embed([item["question"] for item in items], "query")
    hits, reciprocal = 0, []
    for item, vector in zip(items, vectors):
        rows = store.search(repo["slug"], space, vector, 10)
        rank = first_rank(rows, item["expected"])
        hits += rank is not None and rank <= 5
        reciprocal.append(1 / rank if rank else 0.0)
        top = rows[0] if rows else None
        print(f"rank {rank or '>10':>4}  {item['question']}\n"
              f"        top: {top['breadcrumb']} ({top['path']}, {top['distance']:.3f})"
              if top else f"rank  -    {item['question']} (no results)")
    print(f"hit@5 = {hits}/{len(items)}, MRR@10 = {sum(reciprocal) / len(items):.2f}")


if __name__ == "__main__":
    main()
