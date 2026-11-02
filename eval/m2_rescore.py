"""Re-score a stored M2 model comparison offline (no API calls): strict vs lenient citation
parsing, per model.

Run: python eval/m2_rescore.py eval/results/m2_models_2026-11-02.json

Runs from before `raw_answer` was stored are rebuilt from their markdown: each server-made
[n](cite:n) goes back to the [path:start-end] it was parsed from (the strict form), and
everything the strict parser left alone is still there verbatim.
Fallback rule (fixed 2026-11-02, before re-scoring): gpt-oss is the configured fallback only
if its lenient validity is >= ~80% of qwen's, with no new failure modes.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from codeask.answer import Block, rewrite

QUESTIONS = Path(__file__).parent / "m2_models.json"


def raw_text(run: dict) -> str:
    if "raw_answer" in run:
        return run["raw_answer"]
    by_n = {c["n"]: c for c in run["citations"]}
    return re.sub(r"\[(\d+)\]\(cite:\1\)", lambda m: "[{path}:{start}-{end}]".format(
        **by_n[int(m.group(1))]), run["answer"])


def blocks_of(run: dict) -> list[Block]:
    blocks = []
    for b in run["blocks"]:
        path, lines = b.rsplit(":", 1)
        start, end = lines.split("-")
        blocks.append(Block(path, int(start), int(end), ""))
    return blocks


def reason(c, blocks: list[Block]) -> str:
    paths = {b.path for b in blocks}
    if c.path in paths:
        return "range outside the supplied lines"
    if any(p.endswith("/" + c.path) for p in paths):
        return "short path"
    return "path not supplied"


def main():
    runs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    expected = {i: q["expected"] for i, q in enumerate(
        json.loads(QUESTIONS.read_text(encoding="utf-8")), 1)}
    totals = defaultdict(Counter)
    reasons = defaultdict(Counter)
    for run in runs:
        if "error" in run:
            continue
        blocks = blocks_of(run)
        for mode in ("strict", "lenient"):
            _, cited, stats = rewrite(raw_text(run), blocks, "https://x", "sha",
                                      lenient=(mode == "lenient"))
            t = totals[(run["model"], mode)]
            t.update(stats)
            t["answers"] += 1
            if expected[run["q"]]:
                t["answerable"] += 1
                t["hits"] += any(c.valid and c.path in expected[run["q"]] for c in cited)
            if mode == "lenient":
                reasons[run["model"]].update(reason(c, blocks) for c in cited if not c.valid)

    def rate(a, b):
        return f"{a}/{b} ({a / b:.0%})" if b else f"{a}/0"

    lines = ["| Model | Mode | Parsed / attempted brackets | Valid / cited | Expected file hit |",
             "|---|---|---|---|---|"]
    validity = {}
    for (model, mode), t in sorted(totals.items()):
        cited = t["valid"] + t["unverified"]
        validity[(model, mode)] = t["valid"] / cited if cited else 0.0
        lines.append(f"| {model} | {mode} | {rate(t['markers'], t['attempted'])} | "
                     f"{rate(t['valid'], cited)} | {rate(t['hits'], t['answerable'])} |")
    lines += ["", "Unverified citations (lenient), by cause:"]
    lines += [f"- {m}: {dict(r) or 'none'}" for m, r in sorted(reasons.items())]
    qwen = validity.get(("qwen/qwen3.8-27b", "lenient"), 0.0)
    gpt = validity.get(("openai/gpt-oss-120b", "lenient"), 0.0)
    ratio = gpt / qwen if qwen else 0.0
    lines += ["", f"Fallback rule: gpt-oss lenient validity {gpt:.0%} vs qwen {qwen:.0%} -> "
              f"{ratio:.0%} of qwen's ({'meets' if ratio >= 0.8 else 'misses'} the ~80% bar; "
              "new failure modes judged from the causes above)"]
    out = Path(sys.argv[1]).with_name(Path(sys.argv[1]).stem + "_rescore.md")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
