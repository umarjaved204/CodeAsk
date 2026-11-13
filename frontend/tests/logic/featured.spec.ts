// The static featured list has the fields the page expects (PLAN.md slice 5 step 1). Its match
// with the backend's pins is checked by backend/tests/test_featured.py.
import { expect, test } from "@playwright/test";

import featured from "../../data/featured.json";
import { DEFAULT_REPO, FEATURED, repoAddress, repoFromSearch } from "../../lib/featured";

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

// ?repo= (PLAN.md Q77): case-insensitive, the static list the only authority.
test("repoFromSearch names a featured repo however it is spelled or encoded", () => {
  expect(repoFromSearch("?repo=psf/requests")).toBe("psf/requests");
  expect(repoFromSearch("?repo=psf%2Frequests")).toBe("psf/requests");
  expect(repoFromSearch("?repo=PSF/Requests")).toBe("psf/requests");
  expect(repoFromSearch("?other=1&repo=pallets/itsdangerous")).toBe("pallets/itsdangerous");
});

test("repoFromSearch gives null for anything that isn't a featured repo", () => {
  for (const search of ["", "?", "?repo=", "?repo=octo/empty", "?repo=psf", "?repo=psf/requests/x",
                        "?repo=https://github.com/psf/requests", "?r=psf/requests"]) {
    expect(repoFromSearch(search), search).toBeNull();
  }
});

test("repoAddress: plain / for the default repo, ?repo= for the others", () => {
  expect(repoAddress(DEFAULT_REPO)).toBe("/");
  expect(repoAddress("psf/requests")).toBe("/?repo=psf/requests");
  for (const { slug } of FEATURED) expect(repoFromSearch(repoAddress(slug).slice(1)) ?? DEFAULT_REPO).toBe(slug);
});
