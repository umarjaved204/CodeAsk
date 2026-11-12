"""The shipped pre-generated answers, offline (slice 5, build step 7; run by check.ps1).

Every exported repo folder (frontend/data/examples/<owner>__<name>/index.json) must list only
answers that pass, flagship first, for the pinned commit, with questions equal to the frozen set.
Folders without an index.json haven't been exported yet and aren't shipped by the frontend.
"""

import json
from pathlib import Path

import pytest

from codeask import config
from codeask.pregen import INDEX, ROOT, flagship_misses, grade_problems, passes

EXAMPLES = ROOT / "frontend" / "data" / "examples"
FOLDERS = sorted(p for p in EXAMPLES.iterdir() if p.is_dir()) if EXAMPLES.is_dir() else []


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_every_folder_is_a_featured_repo(folder):
    assert folder.name in {s.replace("/", "__") for s in config.FEATURED_SHAS}


INDEXES = [f / INDEX for f in FOLDERS if (f / INDEX).exists()]


@pytest.mark.parametrize("index_path", INDEXES, ids=lambda p: p.parent.name)
def test_an_exported_index_lists_only_passing_answers_for_the_pin(index_path):
    index = read(index_path)
    slug = index["repo"]
    assert index_path.parent.name == slug.replace("/", "__")
    assert index["commit_sha"] == config.FEATURED_SHAS[slug]
    frozen = {e["id"]: e["question"] for e in read(
        ROOT / "eval" / "m2d_questions" / f"{index_path.parent.name}.json")["questions"]}
    ids = [q["id"] for q in index["questions"]]
    assert ids and len(ids) == len(set(ids)) and index["flagship"] == ids[0]
    for q in index["questions"]:
        record = read(index_path.parent / f"{q['id']}.json")
        assert q["question"] == frozen[q["id"]] == record["question"]
        assert record["commit_sha"] == index["commit_sha"]
        assert grade_problems(record) == [] and passes(record), q["id"]
    lead = read(index_path.parent / f"{ids[0]}.json")
    assert (index["flagship_note"] is None) == (flagship_misses(lead) == [])


# ---------- the generated modules (step 8, D1) ----------
def lf(path: Path) -> str:
    """A checkout may hold CRLF (core.autocrlf); the generator writes LF."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_sets_ts_is_exactly_what_export_generates_from_the_exported_folders():
    from codeask.pregen import SETS, exported_slugs, render_sets

    slugs = exported_slugs(EXAMPLES)
    assert lf(EXAMPLES / SETS) == render_sets(slugs)
    featured = {f["slug"] for f in read(ROOT / "frontend" / "data" / "featured.json")}
    assert set(slugs) <= featured


@pytest.mark.parametrize("index_path", INDEXES, ids=lambda p: p.parent.name)
def test_each_set_ts_is_exactly_what_export_generates_from_its_index(index_path):
    from codeask.pregen import render_set

    assert lf(index_path.parent / "set.ts") == render_set(read(index_path))
