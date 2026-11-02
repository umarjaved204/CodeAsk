"""M2 slice 2: compare packer variants offline on the saved candidates (PLAN.md Q20).

Run: python eval/m2_pack_compare.py eval/results/m2_candidates_<date>.json eval/m2_expected.json

No network. Each variant packs every question's saved top-K with the real pack() (merging and
outlines included) and is scored against the expected chunks, fixed beforehand (Q27). An
expected range counts as packed when every non-blank line of it lies inside the packed
blocks. Non-blank = inside some chunk of the file (every non-blank line is in exactly one).
Rule (Q20): the simplest variant that packs all required chunks wins; 2,500 only with a
recall gain.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from codeask.answer import pack

# (name, cap, soft_cap), simplest last.
CAPS = [("hard cap 3", 3, False), ("soft cap 3", 3, True), ("cap 5", 5, False),
        ("no cap", None, False)]
BUDGETS = [2_000, 2_500]


def covered(expected: dict, blocks, file_rows: list[dict]) -> bool:
    chunks = [f for f in file_rows if f["path"] == expected["path"]]
    assert chunks, f"no file_chunks for {expected['path']}: run --add-file-chunks first"
    for line in range(expected["start"], expected["end"] + 1):
        non_blank = any(f["start_line"] <= line <= f["end_line"] for f in chunks)
        if non_blank and not any(b.path == expected["path"] and b.start <= line <= b.end
                                 for b in blocks):
            return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("candidates", type=Path)
    parser.add_argument("expected", type=Path)
    parser.add_argument("--show", type=int, metavar="Q",
                        help="print question Q's packing (default cap) at each budget instead")
    args = parser.parse_args()
    data = json.loads(args.candidates.read_text(encoding="utf-8"))
    expected = {q["q"]: q for q in json.loads(args.expected.read_text(encoding="utf-8"))
                ["questions"]}
    file_rows = data["file_chunks"]

    if args.show:
        (q,) = [q for q in data["questions"] if q["q"] == args.show]
        for budget in BUDGETS:
            packed = pack(q["candidates"], file_rows, budget=budget)
            print(f"budget {budget:,}: estimate {packed.estimate}")
            print("  packed: " + ", ".join(f"{b.path.split('/')[-1]}:{b.start}-{b.end}"
                                           for b in packed.blocks))
            print("  dropped: " + ", ".join(f"{ref.split('/')[-1]} ({why})"
                                            for ref, why in packed.dropped))
        return

    print("| Budget | Variant | Required packed | Missing required | Supporting packed | "
          "Mean estimate | Mean blocks |")
    print("|---|---|---|---|---|---|---|")
    for budget in BUDGETS:
        for name, cap, soft in CAPS:
            req = sup = req_n = sup_n = est = n_blocks = 0
            missing = []
            for q in data["questions"]:
                packed = pack(q["candidates"], file_rows, budget=budget, cap=cap, soft_cap=soft)
                est, n_blocks = est + packed.estimate, n_blocks + len(packed.blocks)
                exp = expected[q["q"]]
                for e in exp["required"]:
                    req_n += 1
                    if covered(e, packed.blocks, file_rows):
                        req += 1
                    else:
                        missing.append(f"Q{q['q']} {e['name']}")
                for e in exp["supporting"]:
                    sup_n += 1
                    sup += covered(e, packed.blocks, file_rows)
            n = len(data["questions"])
            print(f"| {budget:,} | {name} | {req}/{req_n} | {'; '.join(missing) or 'none'} | "
                  f"{sup}/{sup_n} | {est / n:.0f} | {n_blocks / n:.1f} |")


if __name__ == "__main__":
    main()
