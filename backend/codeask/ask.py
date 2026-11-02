"""Answer one question about an ingested repo, with validated citations (M2 slice 1).

Run: python -m codeask.ask pallets/itsdangerous "How is the signing key derived?"
     python -m codeask.ask pallets/itsdangerous "..." --model openai/gpt-oss-120b
     python -m codeask.ask pallets/itsdangerous "..." --save frontend/data/examples/x.json

ask() is the whole pipeline after embedding: the comparison script and the API reuse it.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

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


def evidence(context: list[dict], citations: list[dict],
             max_chars: int = config.EVIDENCE_MAX_CHARS) -> tuple[list[dict], list[dict]]:
    """The supplied blocks the code panel needs (Q30), and the citations with `block`: an index
    into those blocks. Only blocks that contain a valid citation, each sent once, in the order
    of their first citation; raw lines, exactly what the model saw. A block that would push
    the total past `max_chars` is left out (a defensive cap: the context budget already bounds
    it); its citations then get `block: None` and the panel offers only the GitHub link."""
    blocks, index, used, out = [], {}, 0, []
    for c in citations:
        i = None
        if c["valid"]:
            i = next(k for k, b in enumerate(context) if b["path"] == c["path"]
                     and b["start"] <= c["start"] <= c["end"] <= b["end"])
            if i not in index and used + len(context[i]["content"]) <= max_chars:
                index[i] = len(blocks)
                blocks.append(context[i])
                used += len(context[i]["content"])
        out.append({**c, "block": index.get(i)})
    return blocks, out


def public_view(result: dict) -> dict:
    """What the browser gets: no raw answer, usage or rate-limit headers, and only the context
    blocks that hold a valid citation. An ungrounded answer's text, citations and blocks are
    withheld (Q23); the UI shows "No cited answer" plus the possibly relevant files."""
    grounded = result["grounded"]
    blocks, citations = evidence(result["context"], result["citations"]) if grounded else ([], [])
    return {"grounded": grounded,
            "answer": result["answer"] if grounded else None,
            "citations": citations,
            "blocks": blocks,
            "possibly_relevant": result["possibly_relevant"],
            "model": result["model"], "prompt_version": result["prompt_version"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("slug", help="owner/name, as ingested")
    parser.add_argument("question")
    parser.add_argument("--model", default=config.GROQ_MODEL)
    parser.add_argument("--save", type=Path, help="write a pre-generated answer fixture here")
    parser.add_argument("--attempt", type=int, default=1,
                        help="which live run of this question this is (no re-rolls)")
    parser.add_argument("--attempt-note", help="what happened to earlier attempts, if any")
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
    if args.save:
        record = fixture(result, repo, args.question, args.model, args.attempt,
                         args.attempt_note, datetime.now(timezone.utc))
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        print(f"\nsaved {args.save} (grade it before the page calls it checked)")


def fixture(result: dict, repo: dict, question: str, model: str, attempt: int,
            attempt_note: str | None, now: datetime) -> dict:
    """A pre-generated answer for the frontend (slice 3; slice 5 makes the reviewed set): the
    public view plus everything needed to judge it honestly. `grade` starts empty: the author
    fills it in (correct / grounded / citations valid, by whom, when), and only then may the
    page say "checked by the author"."""
    return {
        "question": question,
        "repo": repo["slug"], "repo_url": repo["url"], "commit_sha": repo["commit_sha"],
        "generated_at": now.isoformat(timespec="seconds"),
        "model": result["model"], "prompt_version": result["prompt_version"],
        "generation": {"temperature": config.ANSWER_TEMPERATURE,
                       "max_completion_tokens": config.ANSWER_MAX_TOKENS,
                       "model_options": config.GROQ_MODEL_OPTIONS.get(model, {})},
        "packer": {"retrieve_k": config.RETRIEVE_K, "budget": config.CONTEXT_BUDGET_TOKENS,
                   "per_file_cap": config.PER_FILE_CAP,
                   "merge_max_gap_lines": config.MERGE_MAX_GAP_LINES},
        "usage": result["usage"], "retries_429": result["retries"],
        # Which live run this is: the first is used, no re-rolls (PLAN.md Q34).
        "attempt": attempt, "attempt_note": attempt_note,
        "grade": None,
        "response": public_view(result),
    }


if __name__ == "__main__":
    main()
