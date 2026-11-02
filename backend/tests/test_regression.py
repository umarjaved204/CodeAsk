"""Packer regression on real data, offline: the slice 2 candidates saved by
eval/m2_candidates.py and the expected chunks fixed beforehand (eval/m2_expected.json, Q27).
"""

import json
from pathlib import Path

from codeask.answer import pack

EVAL = Path(__file__).resolve().parents[2] / "eval"
CANDIDATES = EVAL / "results" / "m2_candidates_2026-11-03.json"


def covered(expected, blocks, file_rows):
    """Every non-blank line (= inside some chunk of the file) lies in a packed block."""
    chunks = [f for f in file_rows if f["path"] == expected["path"]]
    return bool(chunks) and all(
        any(b.path == expected["path"] and b.start <= line <= b.end for b in blocks)
        for line in range(expected["start"], expected["end"] + 1)
        if any(f["start_line"] <= line <= f["end_line"] for f in chunks))


def test_key_rotation_context_includes_verify_signature_and_derive_key():
    """Slice 1's Q5 context lacked verify_signature, so both models speculated (PLAN.md)."""
    data = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    expected = json.loads((EVAL / "m2_expected.json").read_text(encoding="utf-8"))
    (q5,) = [q for q in data["questions"] if q["q"] == 5]
    (exp,) = [q for q in expected["questions"] if q["q"] == 5]
    assert data["commit_sha"] == expected["commit_sha"]
    blocks = pack(q5["candidates"], data["file_chunks"]).blocks  # the config defaults
    names = {e["name"] for e in exp["required"]}
    assert "Signer > verify_signature" in names
    assert [e["name"] for e in exp["required"]
            if not covered(e, blocks, data["file_chunks"])] == []
