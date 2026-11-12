// The suggested questions' sets (PLAN.md slice 5, step 8): which set ships with the page, which
// load later, and that a repo with no export is "none", never an error (step 8 review, item 1).
import { expect, test } from "@playwright/test";

import { LOADERS } from "../../data/examples/sets";
import { DEFAULT_REPO } from "../../lib/featured";
import { DEFAULT_SET, loadSet, shownId, storedAnswer, type Loaders } from "../../lib/stored";
import type { StoredSet } from "../../lib/types";

const other: StoredSet = {
  index: { repo: "o/r", commit_sha: "a".repeat(40), exported_at: "2026-11-13T10:00:00+00:00",
           flagship: "q2", flagship_note: null,
           questions: [{ id: "q2", question: "Two?" }, { id: "q1", question: "One?" }] },
  answers: { q1: DEFAULT_SET.answers[DEFAULT_SET.index.flagship],
             q2: DEFAULT_SET.answers[DEFAULT_SET.index.flagship] },
};

test("the set that ships with the page is the default repo's, and every listed answer is in it", () => {
  expect(DEFAULT_SET.index.repo).toBe(DEFAULT_REPO);
  expect(DEFAULT_SET.index.questions[0].id).toBe(DEFAULT_SET.index.flagship);
  for (const q of DEFAULT_SET.index.questions) {
    expect(DEFAULT_SET.answers[q.id]?.question).toBe(q.question);
  }
});

test("the default repo's set needs no loader; an exported repo loads through its own", async () => {
  let calls = 0;
  const loaders: Loaders = { "o/r": async () => { calls += 1; return { default: other }; } };
  expect(await loadSet(DEFAULT_REPO, loaders)).toEqual({ kind: "set", set: DEFAULT_SET });
  expect(calls).toBe(0);
  expect(await loadSet("o/r", loaders)).toEqual({ kind: "set", set: other });
  expect(calls).toBe(1);
});

test("a repo with no export is none, not an error", async () => {
  expect(await loadSet("psf/requests", {})).toEqual({ kind: "none" });
});

test("a chunk that fails to load rejects, so the page can keep its view and offer a retry", async () => {
  const loaders: Loaders = { "o/r": () => Promise.reject(new Error("ChunkLoadError")) };
  await expect(loadSet("o/r", loaders)).rejects.toThrow("ChunkLoadError");
});

test("every generated loader is for a featured repo", async () => {
  const { FEATURED } = await import("../../lib/featured");
  const featured = new Set(FEATURED.map((r) => r.slug));
  for (const slug of Object.keys(LOADERS)) expect(featured.has(slug)).toBe(true);
});

test("the answer shown is the chosen one if the set has it, else the flagship", () => {
  expect(shownId(other, null)).toBe("q2");
  expect(shownId(other, "q1")).toBe("q1");
  expect(shownId(other, "q9")).toBe("q2"); // a choice from another repo's set
  expect(storedAnswer(other, "q1")).toBe(other.answers.q1);
});
