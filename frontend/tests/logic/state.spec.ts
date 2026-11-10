import { expect, test } from "@playwright/test";

import type { Failure } from "../../lib/api";
import {
  IDLE, WAKING_GIVE_UP_MS, askReducer, canSubmit, connectionReducer, type Ask, type AskEvent,
} from "../../lib/state";
import type { AskResponse } from "../../lib/types";

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
      .toMatchObject({ kind: "busy", retryAt: 15_000 });
    expect(run([submit(1), { type: "failure", requestId: 1, at: 2_000, failure: busy(null) }]))
      .toMatchObject({ kind: "busy", retryAt: 62_000 });
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
