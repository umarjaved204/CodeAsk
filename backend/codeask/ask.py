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
from codeask.answer import PROMPT_VERSION, build_messages, estimate_tokens, pack, rewrite


def ask(store, llm, repo: dict, question: str, vector: list[float]) -> dict:
    t0 = time.perf_counter()
    rows = store.search(repo["slug"], repo["settings"]["space"], vector, config.RETRIEVE_K)
    blocks = pack(rows)
    t1 = time.perf_counter()
    reply = llm.chat(build_messages(question, blocks, tag=secrets.token_hex(8)))
    markdown, citations, stats = rewrite(reply.text, blocks, repo["url"], repo["commit_sha"])
    packed = {(b.path, b.start) for b in blocks}
    return {
        "answer": markdown,
        "raw_answer": reply.text,  # for offline re-scoring; never sent to the browser
        "citations": [asdict(c) for c in citations],
        "stats": stats,
        "blocks": [f"{b.path}:{b.start}-{b.end}" for b in blocks],
        # The exact context the model saw, so answers can be graded for groundedness later.
        "context": [asdict(b) for b in blocks],
        # Voyage-token estimate of the context only; compare with usage.prompt_tokens
        # (Groq's tokenizer, plus system prompt and question) to calibrate the packer.
        "context_estimate": sum(estimate_tokens(r) for r in rows
                                if (r["path"], r["start_line"]) in packed),
        "model": reply.model,
        "prompt_version": PROMPT_VERSION,
        "usage": reply.usage,
        "headers": reply.headers,
        "reasoning_chars": len(reply.reasoning or ""),
        "timings_s": {"retrieve": round(t1 - t0, 2), "llm": reply.latency_s},
        "retries": reply.retries,
    }


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

    print(result["answer"], "\n")
    for c in result["citations"]:
        mark = "ok        " if c["valid"] else "UNVERIFIED"
        print(f"[{c['n']}] {mark} {c['path']}:{c['start']}-{c['end']}  {c['url'] or ''}")
    print(f"\ncontext: {', '.join(result['blocks'])}")
    print(f"stats: {result['stats']}  model: {result['model']}  retries: {result['retries']}")
    print(f"usage: {result['usage']}")
    print(f"context estimate (Voyage tokens): {result['context_estimate']}  "
          f"reasoning chars: {result['reasoning_chars']}")
    print(f"timings: embed {embed_s:.2f} s, {result['timings_s']}")
    print(f"rate-limit headers: {result['headers']}")


if __name__ == "__main__":
    main()
