import { expect, test } from "@playwright/test";

import type { Failure } from "../../lib/api";
import {
  LOADING_SLOW_MS, WAKING_SLOW_MS, aboutTime, canRetry, connectionMessage, dailyLimitMessage,
  errorMessage, loadingMessage, pausedMessage, perVisitorMessage, provenance, serviceNote,
} from "../../lib/messages";
import type { Ask } from "../../lib/state";
import type { Example, Service } from "../../lib/types";

function api(code: string, requestId: string | null = "a1b2c3d4", retryAfterS: number | null = null): Failure {
  return { kind: "api", status: 503, code, message: "", requestId, retryAfterS } as Failure;
}

const example = {
  generated_at: "2026-11-02T21:36:45+00:00", model: "qwen/qwen3.8-27b",
  commit_sha: "672971d66a2ef9f85151e53283113f33d642dabd", grade: null,
} as Example;

test("the pre-generated label is a sentence, in UTC, and names who checked it", () => {
  const base = "Example answer, generated 2 Nov 2026 with qwen3.8-27b on commit 672971d.";
  const grade = (reviewer: "claude" | "author") =>
    ({ reviewer, note: "never shown in the label" }) as Example["grade"];
  expect(provenance(example)).toBe(base);
  expect(provenance({ ...example, grade: grade("claude") })).toBe(
    `${base} Claims and citations checked against the cited code by Claude; not yet reviewed by the author.`);
  // Names what was checked, so it can't be read as "complete" (Q37, amended in slice 5).
  expect(provenance({ ...example, grade: grade("author") })).toBe(
    `${base} Claims and citations checked by the author; the answer may leave things out.`);
});

test("waking changes its wording after 35 seconds", () => {
  const waking = { kind: "waking", since: 1_000 } as const;
  expect(connectionMessage(waking, 1_000 + WAKING_SLOW_MS - 1)).toMatch(/^Waking up/);
  expect(connectionMessage(waking, 1_000 + WAKING_SLOW_MS)).toMatch(/^Still starting/);
});

test("a connected or unknown server says nothing", () => {
  expect(connectionMessage({ kind: "up" }, 0)).toBeNull();
  expect(connectionMessage({ kind: "unknown" }, 0)).toBeNull();
});

test("loading escalates after 12 seconds", () => {
  expect(loadingMessage(LOADING_SLOW_MS - 1)).toMatch(/^Answering/);
  expect(loadingMessage(LOADING_SLOW_MS)).toMatch(/^Still working/);
});

test("server errors give the request id, generically", () => {
  expect(errorMessage(api("internal_error"), "a/b", true))
    .toBe("The server couldn’t answer (request a1b2c3d4). Try again.");
  expect(errorMessage(api("timeout", null), "a/b", true))
    .toBe("The server couldn’t answer. Try again.");
});

test("no response is offline or unreachable, by the browser's own state", () => {
  expect(errorMessage({ kind: "unreachable" }, "a/b", false)).toMatch(/^You’re offline/);
  expect(errorMessage({ kind: "unreachable" }, "a/b", true)).toBe("Can’t reach the server.");
});

// Step 5, W9: the page's own wording uses curly apostrophes, never straight ones.
test("UI wording uses curly apostrophes", () => {
  const failures = ["internal_error", "paused", "daily_limit", "per_ip_limit"]
    .map((code) => errorMessage(api(code, "a1b2c3d4", 3_600), "a/b", true));
  const offline = errorMessage({ kind: "unreachable" }, "a/b", false);
  const unreachable = errorMessage({ kind: "unreachable" }, "a/b", true);
  for (const text of [...failures, offline, unreachable]) expect(text, text).not.toContain("'");
});

test("not found names the repo", () => {
  expect(errorMessage(api("not_found"), "a/b", true)).toBe("a/b is no longer available here.");
});

test("retry is offered only where it can help", () => {
  expect(canRetry(api("internal_error"))).toBe(true);
  expect(canRetry({ kind: "unreachable" })).toBe(true);
  for (const code of ["paused", "daily_limit", "per_ip_limit", "model_unavailable", "not_found"]) {
    expect(canRetry(api(code)), code).toBe(false);
  }
});

// ---------- slice 4: the Q45 messages (exact text) and "about N" (step 8) ----------
test("about N: up to the next 5 minutes under an hour, then the nearest hour, at least 1", () => {
  const cases: [number, string][] = [
    [0, "about 5 minutes"], [1, "about 5 minutes"], [300, "about 5 minutes"],
    [301, "about 10 minutes"], [3_299, "about 55 minutes"], [3_301, "about 1 hour"],
    [3_599, "about 1 hour"], [3_600, "about 1 hour"], [3_660, "about 1 hour"],
    [5_399, "about 1 hour"], [5_400, "about 2 hours"], [7_200, "about 2 hours"],
    [86_400, "about 24 hours"],
  ];
  for (const [seconds, text] of cases) expect(aboutTime(seconds), String(seconds)).toBe(text);
});

const DAILY = "Live questions are used up for now. Try again in about 2 hours. This demo runs on a " +
  "free API tier, so live questions are capped each day.";
const EXAMPLE_TAIL = " The suggested questions still work.";

test("each message says the suggested questions still work only when they are on screen", () => {
  expect(pausedMessage(false)).toBe("Live questions are paused right now.");
  expect(pausedMessage(true)).toBe(`Live questions are paused right now.${EXAMPLE_TAIL}`);
  expect(dailyLimitMessage(7_200, false)).toBe(DAILY);
  expect(dailyLimitMessage(7_200, true)).toBe(DAILY + EXAMPLE_TAIL);
  expect(perVisitorMessage(1_800, false)).toBe(
    "You’ve reached the daily limit of live questions for one visitor. Try again in about 30 minutes.");
  expect(perVisitorMessage(1_800, true)).toBe(
    "You’ve reached the daily limit of live questions for one visitor. Try again in about 30 minutes." +
    EXAMPLE_TAIL);
  // Without a usable Retry-After, no time is promised.
  expect(dailyLimitMessage(null, false)).toBe("Live questions are used up for now. This demo runs " +
    "on a free API tier, so live questions are capped each day.");
});

test("a refusal says the suggested questions still work only when the list is on screen", () => {
  expect(errorMessage(api("paused"), "a/b", true)).toBe("Live questions are paused right now.");
  expect(errorMessage(api("paused"), "a/b", true, true)).toBe(
    `Live questions are paused right now.${EXAMPLE_TAIL}`);
  expect(errorMessage(api("daily_limit", "r", 7_200), "a/b", true)).toBe(DAILY);
  expect(errorMessage(api("daily_limit", "r", 7_200), "a/b", true, true)).toBe(DAILY + EXAMPLE_TAIL);
  expect(errorMessage(api("per_ip_limit", "r", 10_800), "a/b", true)).toBe(
    "You’ve reached the daily limit of live questions for one visitor. Try again in about 3 hours.");
  expect(errorMessage(api("model_unavailable"), "a/b", true)).toBe(
    "Live answers are unavailable right now.");
  expect(errorMessage(api("model_unavailable"), "a/b", true, true)).toBe(
    `Live answers are unavailable right now.${EXAMPLE_TAIL}`);
  // A removed repo or a server error never adds it: trying a suggestion isn't the advice there.
  expect(errorMessage(api("not_found"), "a/b", true, true)).toBe("a/b is no longer available here.");
});

test.describe("the composer's service line: one owner per message", () => {
  const asked = { repo: "a/b", question: "q?" };
  const idle: Ask = { kind: "idle", settling: null };
  const paused: Service = { status: "paused", retryAfterS: null };
  const daily: Service = { status: "daily_limit", retryAfterS: 7_200 };
  const refused = (code: string): Ask => ({ kind: "error", failure: api(code, "r", 7_200), ...asked });

  test("open means no line", () => {
    expect(serviceNote({ status: "ok", retryAfterS: null }, idle, true)).toBeNull();
  });

  test("on load it speaks, with the example sentence only when an example is shown", () => {
    expect(serviceNote(paused, idle, true)).toBe(pausedMessage(true));
    expect(serviceNote(paused, idle, false)).toBe(pausedMessage(false));
    expect(serviceNote(daily, idle, true)).toBe(DAILY + EXAMPLE_TAIL);
  });

  test("quiet while the question's own status shows the same refusal, never both", () => {
    expect(serviceNote(paused, refused("paused"), false)).toBeNull();
    expect(serviceNote(daily, refused("daily_limit"), false)).toBeNull();
  });

  test("a different failure doesn't silence it, so the line is never lost", () => {
    expect(serviceNote(paused, refused("internal_error"), false)).toBe(pausedMessage(false));
    expect(serviceNote(paused, refused("per_ip_limit"), false)).toBe(pausedMessage(false));
  });
});
