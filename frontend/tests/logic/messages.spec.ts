import { expect, test } from "@playwright/test";

import type { Failure } from "../../lib/api";
import {
  LOADING_SLOW_MS, WAKING_SLOW_MS, canRetry, connectionMessage, errorMessage, loadingMessage,
  provenance,
} from "../../lib/messages";
import type { Example } from "../../lib/types";

function api(code: string, requestId: string | null = "a1b2c3d4"): Failure {
  return { kind: "api", status: 503, code, message: "", requestId, retryAfterS: null } as Failure;
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
    `${base} Checked against the cited code by Claude; not yet reviewed by the author.`);
  expect(provenance({ ...example, grade: grade("author") })).toBe(`${base} Checked by the author.`);
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
    .toBe("The server couldn't answer (request a1b2c3d4). Try again.");
  expect(errorMessage(api("timeout", null), "a/b", true))
    .toBe("The server couldn't answer. Try again.");
});

test("no response is offline or unreachable, by the browser's own state", () => {
  expect(errorMessage({ kind: "unreachable" }, "a/b", false)).toMatch(/^You're offline/);
  expect(errorMessage({ kind: "unreachable" }, "a/b", true)).toBe("Can't reach the server.");
});

test("not found names the repo", () => {
  expect(errorMessage(api("not_found"), "a/b", true)).toBe("a/b is no longer available here.");
});

test("retry is offered only where it can help", () => {
  expect(canRetry(api("internal_error"))).toBe(true);
  expect(canRetry({ kind: "unreachable" })).toBe(true);
  for (const code of ["daily_cap", "model_unavailable", "not_found"]) {
    expect(canRetry(api(code))).toBe(false);
  }
});
