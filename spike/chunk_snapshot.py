"""Prove a chunker refactor doesn't change code chunking.

Snapshots (path, start_line, end_line, content_hash) for every chunk of every Python and
JS/TS file in the cloned repos (tests included), then compares a later run against it. Uses a
fixed ~4 chars/token counter, so it is deterministic and needs no keys. Windows are run in
their naive form (window_prefer_blank_lines off, when that setting exists), so the comparison
isolates the refactor from deliberate changes to windowing.

Run: python spike/chunk_snapshot.py save spike/code_chunks_before.json
     python spike/chunk_snapshot.py compare spike/code_chunks_before.json
"""

import dataclasses
import json
import sys
from pathlib import Path

from codeask.chunker import ChunkSettings, chunk_file
from codeask.filters import scan_repo
from codeask.ingest import content_hash

REPOS = Path(__file__).resolve().parents[1] / "repos"
CODE_EXT = (".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".tsx")
NAIVE = ChunkSettings(**({"window_prefer_blank_lines": False}
                         if "window_prefer_blank_lines" in
                         {f.name for f in dataclasses.fields(ChunkSettings)} else {}))


def count(text):
    return (len(text) + 3) // 4


def snapshot():
    rows = []
    for repo in sorted(p for p in REPOS.iterdir() if p.is_dir()):
        for f in scan_repo(repo, include_tests=True).files:
            if not f.path.endswith(CODE_EXT):
                continue
            for c in chunk_file(f.path, f.text, count, NAIVE).chunks:
                rows.append([repo.name, c.path, c.start_line, c.end_line,
                             content_hash("snapshot", c.embed_text)])
    return rows


def main():
    mode, path = sys.argv[1], Path(sys.argv[2])
    rows = snapshot()
    if mode == "save":
        path.write_text(json.dumps(rows, indent=0), encoding="utf-8")
        print(f"saved {len(rows)} chunks from {len({(r[0], r[1]) for r in rows})} code files")
        return
    all_before = [tuple(r) for r in json.loads(path.read_text(encoding="utf-8"))]
    all_after = [tuple(r) for r in rows]
    differs = False
    for group, exts in (("python", (".py",)), ("js/ts", CODE_EXT[1:])):
        before = [r for r in all_before if r[1].endswith(exts)]
        after = [r for r in all_after if r[1].endswith(exts)]
        if before == after:
            print(f"{group}: identical ({len(after)} chunks)")
            continue
        differs = True
        removed, added = set(before) - set(after), set(after) - set(before)
        files = {r[:2] for r in removed | added}
        print(f"{group}: DIFFERENT: {len(before)} -> {len(after)} chunks; {len(removed)} removed, "
              f"{len(added)} added, in {len(files)} files")
        for r in sorted(removed)[:5]:
            print("  -", r[:4])
        for r in sorted(added)[:5]:
            print("  +", r[:4])
    sys.exit(1 if differs else 0)


if __name__ == "__main__":
    main()
