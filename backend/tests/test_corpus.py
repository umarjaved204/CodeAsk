"""Real-corpus sweep: chunk every ingestible file of the cloned repos in repos/ and assert the
chunker's invariants on each. Hand-written samples miss what real code does; this doesn't.

Run with output: pytest -s -k corpus
Prints per repo: the chunk-size distribution, how files were chunked, why over-cap units fell
back to windows (IIFE, object literal, shared-line composite, ...) and parse-error files.
Uses the fake token counter, so sizes are approximate (~4 chars/token).
"""

from collections import Counter
from pathlib import Path
from statistics import mean, median

import pytest
from helpers import check_invariants, fake_count

from codeask.chunker import ChunkSettings, chunk_file
from codeask.filters import scan_repo

REPOS = Path(__file__).resolve().parents[2] / "repos"


def percentile(sorted_values, p):
    return sorted_values[min(len(sorted_values) - 1, int(p * len(sorted_values)))]


def test_corpus_sweep():
    repos = sorted(p for p in REPOS.iterdir() if p.is_dir()) if REPOS.is_dir() else []
    if not repos:
        pytest.skip("no cloned repos in repos/")
    settings = ChunkSettings()
    lines = ["", f"{'repo':<22}{'files':>6}{'chunks':>8}{'mean':>7}{'median':>8}{'p95':>6}"
                 f"{'max':>6}{'<60':>6}"]
    details = []
    for repo in repos:
        scan = scan_repo(repo, include_tests=True, include_docs=True)
        sizes, methods, skips, reasons, fallbacks = [], Counter(), Counter(), Counter(), []
        doc_kinds, truncated = Counter(), 0
        for f in scan.files:
            result = chunk_file(f.path, f.text, fake_count, settings)
            methods[result.method] += 1
            reasons.update(result.window_reasons)
            truncated += result.truncated_lines
            if f.path.endswith((".md", ".rst")):
                doc_kinds.update(c.kind for c in result.chunks)
            if result.method == "fallback":
                fallbacks.append(f.path)
            if result.skip_reason:
                skips[result.skip_reason] += 1
                continue
            try:
                check_invariants(f.text, result, settings.max_tokens)
            except AssertionError as error:
                raise AssertionError(f"{repo.name}/{f.path}: {error}") from None
            sizes.extend(c.token_count for c in result.chunks)
        s = sorted(sizes)
        if not s:
            lines.append(f"{repo.name:<22}{len(scan.files):>6}       0")
            continue
        small = sum(1 for x in s if x < settings.min_tokens)
        lines.append(
            f"{repo.name:<22}{len(scan.files):>6}{len(s):>8}{mean(s):>7.0f}{median(s):>8.0f}"
            f"{percentile(s, 0.95):>6}{s[-1]:>6}{small:>6}")
        details.append(f"  {repo.name}: methods {dict(methods)}; skips {dict(skips)}")
        details.append(f"    units windowed: {dict(reasons) or 'none'}")
        details.append(f"    doc chunk kinds: {dict(doc_kinds) or 'none'}; "
                       f"doc lines truncated in embed_text: {truncated}")
        if fallbacks:
            details.append(f"    parse-error fallbacks ({len(fallbacks)}): "
                           f"{', '.join(fallbacks[:8])}{' ...' if len(fallbacks) > 8 else ''}")
    print("\n".join(lines + [""] + details))
