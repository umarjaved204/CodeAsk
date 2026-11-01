"""What an ingest would embed: files, chunks and tokens per category, and the ETA at the
no-card Voyage limits. No API calls (the tokenizer is local).

Run: python -m codeask.count repos/itsdangerous [--tests] [--docs]
"""

from __future__ import annotations

import argparse
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median

from codeask import config
from codeask.chunker import Chunk, ChunkSettings, chunk_file
from codeask.filters import ScanResult, scan_repo


@dataclass
class RepoChunks:
    scan: ScanResult
    chunks: list[tuple[str, Chunk]] = field(default_factory=list)  # (category, chunk)
    methods: Counter = field(default_factory=Counter)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # filter + chunker skips


def chunk_repo(root: Path, count_tokens, include_tests=False, include_docs=False,
               settings: ChunkSettings = ChunkSettings()) -> RepoChunks:
    scan = scan_repo(root, include_tests, include_docs)
    out = RepoChunks(scan, skipped=list(scan.skipped))
    for f in scan.files:
        result = chunk_file(f.path, f.text, count_tokens, settings)
        out.methods[result.method] += 1
        if result.skip_reason:
            out.skipped.append((f.path, result.skip_reason))
        out.chunks.extend((f.category, c) for c in result.chunks)
    return out


def pack_batches(token_counts: list[int], limit: int = config.BATCH_TOKENS) -> list[list[int]]:
    """Greedy, in order: indices grouped into requests of at most `limit` tokens."""
    batches, current, total = [], [], 0
    for i, n in enumerate(token_counts):
        if current and total + n > limit:
            batches.append(current)
            current, total = [], 0
        current.append(i)
        total += n
    if current:
        batches.append(current)
    return batches


def eta_seconds(requests: int) -> int:
    """The pacer sends 3 requests per 65 s window, so N requests take ceil(N/3)-1 windows."""
    if requests == 0:
        return 0
    return (math.ceil(requests / config.VOYAGE_REQUESTS_PER_WINDOW) - 1) \
        * config.VOYAGE_WINDOW_SECONDS


def unique_texts(chunks: list[tuple[str, Chunk]]) -> dict[str, int]:
    """embed_text -> tokens. Identical texts share one embedding, so they're embedded once."""
    return {c.embed_text: c.token_count for _, c in chunks}


def report(name: str, rc: RepoChunks) -> str:
    lines = [f"== {name} =="]
    by_cat = {}
    for cat, c in rc.chunks:
        files, chunks, tokens = by_cat.get(cat, (set(), 0, 0))
        files.add(c.path)
        by_cat[cat] = (files, chunks + 1, tokens + c.token_count)
    lines.append(f"{'category':<10}{'files':>7}{'chunks':>8}{'tokens':>10}")
    for cat in ("source", "test", "doc"):
        if cat in by_cat:
            files, chunks, tokens = by_cat[cat]
            lines.append(f"{cat:<10}{len(files):>7}{chunks:>8}{tokens:>10,}")
    total = sum(c.token_count for _, c in rc.chunks)
    unique = unique_texts(rc.chunks)
    lines.append(f"{'total':<10}{'':>7}{len(rc.chunks):>8}{total:>10,}"
                 f"   (unique texts: {len(unique)} chunks, {sum(unique.values()):,} tokens)")

    sizes = sorted(c.token_count for _, c in rc.chunks)
    if sizes:
        p95 = sizes[min(len(sizes) - 1, int(0.95 * len(sizes)))]
        small = sum(1 for s in sizes if s < config.MIN_TOKENS)
        lines.append(f"chunk tokens: mean {mean(sizes):.0f}, median {median(sizes):.0f}, "
                     f"p95 {p95}, max {sizes[-1]}, under {config.MIN_TOKENS}: {small}")
    lines.append(f"methods: {dict(rc.methods)}")
    excluded = dict(rc.scan.excluded)
    lines.append(f"excluded (category not requested): {excluded or 'none'}; "
                 f"ignored file types: {rc.scan.ignored}")
    if rc.skipped:
        lines.append(f"skipped {len(rc.skipped)}:")
        lines.extend(f"  {path}: {reason}" for path, reason in rc.skipped)

    requests = len(pack_batches(list(unique.values())))
    eta = eta_seconds(requests)
    lines.append(f"embedding (before cache): {requests} requests of <= {config.BATCH_TOKENS:,} "
                 f"tokens -> ETA ~{eta / 60:.1f} min at {config.VOYAGE_REQUESTS_PER_WINDOW} "
                 f"requests per {config.VOYAGE_WINDOW_SECONDS} s")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("repo_dir", type=Path)
    parser.add_argument("--tests", action="store_true", help="include test files")
    parser.add_argument("--docs", action="store_true", help="include docs beyond the README")
    args = parser.parse_args()

    from codeask.tokens import voyage_counter

    started = time.perf_counter()
    rc = chunk_repo(args.repo_dir, voyage_counter(), args.tests, args.docs)
    print(report(args.repo_dir.name, rc))
    print(f"(counted in {time.perf_counter() - started:.1f} s)")


if __name__ == "__main__":
    main()
