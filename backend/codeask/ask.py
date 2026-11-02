"""Answer one question about an ingested repo, with validated citations (M2 slice 1).

Run: python -m codeask.ask pallets/itsdangerous "How is the signing key derived?"
     python -m codeask.ask pallets/itsdangerous "..." --model openai/gpt-oss-120b

ask() is the whole pipeline after embedding: the comparison script and the API reuse it.
"""

from __future__ import annotations

import argparse
import secrets
import sys
import time
from dataclasses import asdict

from codeask import config
from codeask.answer import PROMPT_VERSION, build_messages, pack, possibly_relevant, rewrite


def ask(store, llm, repo: dict, question: str, vector: list[float]) -> dict:
    t0 = time.perf_counter()
    rows = store.search(repo["slug"], repo["settings"]["space"], vector, config.RETRIEVE_K)
    file_rows = store.file_chunks(repo["slug"], list(dict.fromkeys(r["path"] for r in rows)))
    packed = pack(rows, file_rows)
    blocks = packed.blocks
    t1 = time.perf_counter()
    reply = llm.chat(build_messages(question, blocks, secrets.token_hex(8), packed.outlines))
    markdown, citations, stats = rewrite(reply.text, blocks, repo["url"], repo["commit_sha"])
    grounded = stats["valid"] > 0  # Q3/Q9: no valid citation = couldn't ground it
    return {
        "grounded": grounded,
        "possibly_relevant": [] if grounded else possibly_relevant(
            rows, repo["url"], repo["commit_sha"]),
        "answer": markdown,  # kept even when ungrounded, for eval; public_view() withholds it
        "raw_answer": reply.text,  # for offline re-scoring; never sent to the browser
        "citations": [asdict(c) for c in citations],
        "stats": stats,
        "blocks": [f"{b.path}:{b.start}-{b.end}" for b in blocks],
        # The exact context the model saw, so answers can be graded for groundedness later.
        "context": [asdict(b) for b in blocks],
        "outlines": [asdict(o) for o in packed.outlines],
        "dropped": packed.dropped,  # retrieved but not packed, with the reason (M3)
        # Voyage-token estimate of the context only; compare with usage.prompt_tokens
        # (Groq's tokenizer, plus system prompt and question) to calibrate the packer.
        "context_estimate": packed.estimate,
        "model": reply.model,
        "prompt_version": PROMPT_VERSION,
        "usage": reply.usage,
        "headers": reply.headers,
        "reasoning_chars": len(reply.reasoning or ""),
        "timings_s": {"retrieve": round(t1 - t0, 2), "llm": reply.latency_s},
        "retries": reply.retries,
    }


def public_view(result: dict) -> dict:
    """What the browser gets: no raw answer, context, usage or rate-limit headers. An
    ungrounded answer's text and citations are withheld (Q23); the UI shows "couldn't ground
    this in the code" plus the possibly relevant files."""
    grounded = result["grounded"]
    return {"grounded": grounded,
            "answer": result["answer"] if grounded else None,
            "citations": result["citations"] if grounded else [],
            "possibly_relevant": result["possibly_relevant"],
            "model": result["model"], "prompt_version": result["prompt_version"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("slug", help="owner/name, as ingested")
    parser.add_argument("question")
    parser.add_argument("--model", default=config.GROQ_MODEL)
    args = parser.parse_args()

    from codeask.embedder import VoyageEmbedder
    from codeask.llm import GroqClient
    from codeask.store import Store, connect

    store = Store(connect())
    repo = store.repo(args.slug.lower())
    if repo is None:
        sys.exit(f"{args.slug} is not ingested")
    embedder = VoyageEmbedder()
    if repo["settings"]["space"] != embedder.space:
        sys.exit(f"{args.slug} was embedded in {repo['settings']['space']}, "
                 f"but the embedder is {embedder.space}")

    t0 = time.perf_counter()
    (vector,) = embedder.embed([args.question], "query")
    embed_s = time.perf_counter() - t0
    result = ask(store, GroqClient(args.model), repo, args.question, vector)
    total_s = time.perf_counter() - t0

    if not result["grounded"]:
        print("NOT GROUNDED (no valid citation): the API withholds this text. Possibly relevant: "
              + ", ".join(f"{f['path']}:{f['start']}-{f['end']}"
                          for f in result["possibly_relevant"]))
    print(result["answer"], "\n")
    for c in result["citations"]:
        mark = "ok        " if c["valid"] else "UNVERIFIED"
        print(f"[{c['n']}] {mark} {c['path']}:{c['start']}-{c['end']}  {c['url'] or ''}")
    print(f"\ncontext: {', '.join(result['blocks'])}")
    print(f"stats: {result['stats']}  model: {result['model']}  retries: {result['retries']}")
    print(f"usage: {result['usage']}")
    print(f"context estimate (Voyage tokens): {result['context_estimate']}  "
          f"reasoning chars: {result['reasoning_chars']}")
    print(f"timings: embed {embed_s:.2f} s, {result['timings_s']}, total {total_s:.2f} s")
    if result["dropped"]:
        print(f"dropped: {', '.join(f'{ref} ({why})' for ref, why in result['dropped'])}")
    print(f"rate-limit headers: {result['headers']}")


if __name__ == "__main__":
    main()
