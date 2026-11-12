// The static featured list has the fields the page expects (PLAN.md slice 5 step 1). Its match
// with the backend's pins is checked by backend/tests/test_featured.py.
import { expect, test } from "@playwright/test";

import featured from "../../data/featured.json";
import { DEFAULT_REPO, FEATURED } from "../../lib/featured";

test("every featured entry has a slug, its GitHub URL and a full commit SHA", () => {
  expect(featured.length).toBeGreaterThan(0);
  for (const entry of featured) {
    expect(Object.keys(entry).sort()).toEqual(["commit_sha", "slug", "url"]);
    expect(entry.slug).toMatch(/^[a-z0-9._-]+\/[a-z0-9._-]+$/);
    expect(entry.url).toBe(`https://github.com/${entry.slug}`);
    expect(entry.commit_sha).toMatch(/^[0-9a-f]{40}$/);
  }
  expect(new Set(featured.map((e) => e.slug)).size).toBe(featured.length);
});

test("the page's repo list comes from it, with the default repo included", () => {
  expect(FEATURED).toEqual(featured.map(({ slug, url }) => ({ slug, url })));
  expect(FEATURED.map((r) => r.slug)).toContain(DEFAULT_REPO);
});
