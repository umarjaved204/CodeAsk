import { expect, test } from "@playwright/test";

import { SERVICE_OK, type Failure } from "../../lib/api";
import {
  IDLE, WAKING_GIVE_UP_MS, askReducer, canSubmit, connectionReducer, serviceAfterAnswer,
  serviceAfterFailure, shouldRefreshService, type Ask, type AskEvent,
} from "../../lib/state";
import type { AskResponse, Service } from "../../lib/types";

const grounded: AskResponse = {
  grounded: true, answer: "It does X [1](cite:1).", blocks: [], possibly_relevant: [],
  citations: [], model: "m", prompt_version: 3,
};
const ungrounded: AskResponse = { ...grounded, grounded: false, answer: null };

function submit(requestId: number, serverUp = true, repo = "a/b"): AskEvent {
  return { type: "submit", repo, question: "q?", requestId, at: 1_000, serverUp };
}

function run(events: AskEvent[], from: Ask = IDLE): Ask {
  return events.reduce(askReducer, from);
}

// ---------- connection ----------
test.describe("connection", () => {
  test("a status answer means up, from any state", () => {
    expect(connectionReducer({ kind: "unknown" }, { type: "status_ok" })).toEqual({ kind: "up" });
    expect(connectionReducer({ kind: "down" }, { type: "status_ok" })).toEqual({ kind: "up" });
  });

  test("failures are waking until the window runs out, then down", () => {
    let s = connectionReducer({ kind: "unknown" }, { type: "status_failed", at: 0, online: true });
    expect(s).toEqual({ kind: "waking", since: 0 });
    s = connectionReducer(s, { type: "status_failed", at: WAKING_GIVE_UP_MS - 1, online: true });
    expect(s).toEqual({ kind: "waking", since: 0 }); // `since` keeps the first failure
    s = connectionReducer(s, { type: "status_failed", at: WAKING_GIVE_UP_MS, online: true });
    expect(s).toEqual({ kind: "down" });
    s = connectionReducer(s, { type: "status_failed", at: WAKING_GIVE_UP_MS * 2, online: true });
    expect(s).toEqual({ kind: "down" }); // stays down until the visitor retries
  });

  test("a failure while the browser is offline is offline, not waking", () => {
    expect(connectionReducer({ kind: "up" }, { type: "status_failed", at: 5, online: false }))
      .toEqual({ kind: "offline" });
  });

  test("retry after down starts a new waking window", () => {
    expect(connectionReducer({ kind: "down" }, { type: "retry", at: 7 }))
      .toEqual({ kind: "waking", since: 7 });
  });
});

// ---------- ask lifecycle ----------
test.describe("ask", () => {
  test("submit loads, and the matching response answers", () => {
    const s = run([submit(1), { type: "response", requestId: 1, response: grounded }]);
    expect(s).toMatchObject({ kind: "answered", repo: "a/b", question: "q?" });
  });

  test("an ungrounded response is its own state", () => {
    expect(run([submit(1), { type: "response", requestId: 1, response: ungrounded }]).kind)
      .toBe("ungrounded");
  });

  test("submitting while loading does nothing (Enter is ignored)", () => {
    const loading = run([submit(1)]);
    expect(canSubmit(loading)).toBe(false);
    expect(askReducer(loading, submit(2))).toBe(loading);
  });

  test("a stale response for an older request is ignored", () => {
    const s = run([submit(1), { type: "failure", requestId: 1, at: 2_000,
                                failure: { kind: "unreachable" } }, submit(2)]);
    expect(askReducer(s, { type: "response", requestId: 1, response: grounded })).toBe(s);
  });

  test("switching repo mid-request drops the answer and holds Ask until it settles", () => {
    let s = run([submit(1), { type: "switch_repo" }]);
    expect(s).toEqual({ kind: "idle", settling: 1 });
    expect(canSubmit(s)).toBe(false);
    expect(askReducer(s, submit(2, true, "c/d"))).toBe(s); // "Finishing the previous question"
    s = askReducer(s, { type: "response", requestId: 1, response: grounded });
    expect(s).toEqual(IDLE); // the old repo's answer is never shown
    expect(canSubmit(s)).toBe(true);
  });

  test("a question asked while the server wakes waits, then is sent once", () => {
    let s = run([submit(1, false)]);
    expect(s).toMatchObject({ kind: "waiting", question: "q?" });
    expect(canSubmit(s)).toBe(false);
    s = askReducer(s, { type: "send", requestId: 2, at: 30_000 });
    expect(s).toMatchObject({ kind: "loading", requestId: 2, startedAt: 30_000 });
    expect(askReducer(s, { type: "send", requestId: 3, at: 31_000 })).toBe(s); // only once
  });

  test("busy waits for Retry-After, or a minute without it", () => {
    const busy = (retryAfterS: number | null): Failure => ({
      kind: "api", status: 503, code: "busy", message: "", requestId: "r1", retryAfterS });
    expect(run([submit(1), { type: "failure", requestId: 1, at: 2_000, failure: busy(13) }]))
      .toMatchObject({ kind: "busy", retryAt: 15_000, reason: "busy" });
    expect(run([submit(1), { type: "failure", requestId: 1, at: 2_000, failure: busy(null) }]))
      .toMatchObject({ kind: "busy", retryAt: 62_000, reason: "busy" });
  });

  test("a previous question still in flight reuses the busy countdown, with its own reason", () => {
    const inProgress: Failure = { kind: "api", status: 429, code: "in_progress", message: "",
                                  requestId: "r1", retryAfterS: 40 };
    const s = run([submit(1), { type: "failure", requestId: 1, at: 2_000, failure: inProgress }]);
    expect(s).toMatchObject({ kind: "busy", retryAt: 42_000, reason: "in_progress" });
    expect(canSubmit(s)).toBe(true);
  });

  test("the other limits are errors, and Ask stays enabled (Q46 C7)", () => {
    for (const code of ["paused", "daily_limit", "per_ip_limit"] as const) {
      const failure: Failure = { kind: "api", status: 429, code, message: "", requestId: "r",
                                 retryAfterS: 60 };
      const s = run([submit(1), { type: "failure", requestId: 1, at: 2_000, failure }]);
      expect(s, code).toMatchObject({ kind: "error", failure });
      expect(canSubmit(s), code).toBe(true);
    }
  });

  test("other failures are errors that keep the failure for the message", () => {
    const failure: Failure = { kind: "api", status: 500, code: "internal_error", message: "x",
                               requestId: "r9", retryAfterS: null };
    expect(run([submit(1), { type: "failure", requestId: 1, at: 2_000, failure }]))
      .toMatchObject({ kind: "error", failure });
  });

  test("after an answer, a new question can be asked", () => {
    const s = run([submit(1), { type: "response", requestId: 1, response: grounded }]);
    expect(canSubmit(s)).toBe(true);
    expect(askReducer(s, submit(2)).kind).toBe("loading");
  });
});

// ---------- service (Q45, step 8) ----------
test.describe("service", () => {
  const paused: Service = { status: "paused", retryAfterS: null };
  const daily: Service = { status: "daily_limit", retryAfterS: 7_200 };
  const refusal = (code: string, retryAfterS: number | null = null): Failure =>
    ({ kind: "api", status: 429, code, message: "", requestId: "r", retryAfterS }) as Failure;

  test("a paused or daily-limit refusal sets it, so the line follows the newest value", () => {
    expect(serviceAfterFailure(SERVICE_OK, refusal("paused"))).toEqual(paused);
    expect(serviceAfterFailure(paused, refusal("daily_limit", 7_200))).toEqual(daily);
    expect(serviceAfterFailure(daily, refusal("paused"))).toEqual(paused);
  });

  test("other failures leave it as it was", () => {
    for (const failure of [refusal("per_ip_limit", 60), refusal("busy", 13), refusal("internal_error"),
                           { kind: "unreachable" } as Failure]) {
      expect(serviceAfterFailure(paused, failure)).toEqual(paused);
    }
  });

  test("an answer means live questions are open", () => {
    expect(serviceAfterAnswer()).toEqual(SERVICE_OK);
  });

  test("a return to the tab refreshes only a closed service, at most once a minute", () => {
    expect(shouldRefreshService(SERVICE_OK, 0, 10 * 60_000)).toBe(false); // open: never
    expect(shouldRefreshService(paused, 0, 60_000)).toBe(false); // 60 s: not yet
    expect(shouldRefreshService(paused, 0, 60_001)).toBe(true);
    expect(shouldRefreshService(daily, 100_000, 130_000)).toBe(false);
  });
});
