"""The frontend's static featured list must match the backend's pins (PLAN.md Q52).

frontend/data/featured.json is read here, in tests only; the backend never reads it at runtime.
A missing file fails the test (no skip).
"""

import json
from pathlib import Path

from codeask import config

FEATURED_JSON = Path(__file__).resolve().parents[2] / "frontend" / "data" / "featured.json"


def test_featured_json_matches_the_backend_pins():
    entries = json.loads(FEATURED_JSON.read_text(encoding="utf-8"))
    assert {e["slug"]: e["commit_sha"] for e in entries} == config.FEATURED_SHAS
    assert len(entries) == len(config.FEATURED_SHAS)  # no duplicate slugs
    for e in entries:
        assert e["url"] == f"https://github.com/{e['slug']}"


def test_featured_repos_follow_the_pins():
    assert config.FEATURED_REPOS == tuple(config.FEATURED_SHAS)
