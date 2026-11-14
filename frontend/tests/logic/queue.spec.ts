// State 5, queued (PLAN.md Q40, final in Q45; wording: step 8) and the service state /status
// carries: the boundary validation, the wording and the reducer's queue rules. No page.
import { expect, test } from "@playwright/test";

import { SERVICE_OK, pollQueue, readQueue, readService } from "../../lib/api";
import { isQueued, ordinal, queuedAnnouncement, queuedMessage, roundedWait } from "../../lib/messages";
import { IDLE, askReducer, type Ask, type AskEvent } from "../../lib/state";

test.describe("readQueue: the one validation of /status's queue", () => {
  test("a valid place passes, with or without extra fields", () => {
    expect(readQueue({ position: 2, wait_s: 40 })).toEqual({ position: 2, waitS: 40 });
    expect(readQueue({ position: 1, wait_s: 0 })).toEqual({ position: 1, waitS: 0 });
    expect(readQueue({ position: 99, wait_s: 12.5, extra: "x" })).toEqual({ position: 99, waitS: 12.5 });
  });

  test("a bad position means no queue at all", () => {
    for (const position of [-1, 0, 1.5, Number.NaN, Infinity, 100, "2", null, undefined]) {
      expect(readQueue({ position, wait_s: 40 }), String(position)).toBeNull();
    }
    for (const raw of [null, undefined, {}, "2nd", 2, [], true]) {
      expect(readQueue(raw), JSON.stringify(raw)).toBeNull();
    }
  });

  test("a bad wait keeps the position and drops only the seconds", () => {
    for (const wait_s of [undefined, null, -1, Number.NaN, Infinity, "40"]) {
      expect(readQueue({ position: 3, wait_s }), String(wait_s)).toEqual({ position: 3, waitS: null });
    }
  });
});

test.describe("pollQueue", () => {
  const reply = (body: unknown) => async () => new Response(JSON.stringify(body), {
    status: 200, headers: { "content-type": "application/json" } });
  const status = { ok: true, model: "m", model_available: true, prompt_version: 3 };

  test("returns the validated place, or null when nothing waits", async () => {
    expect(await pollQueue(reply({ ...status, queue: { position: 2, wait_s: 40 } }), "http://api"))
      .toEqual({ ok: true, queue: { position: 2, waitS: 40 }, service: SERVICE_OK });
    expect(await pollQueue(reply(status), "http://api"))
      .toEqual({ ok: true, queue: null, service: SERVICE_OK });
    expect(await pollQueue(reply({ ...status, queue: null }), "http://api"))
      .toEqual({ ok: true, queue: null, service: SERVICE_OK });
  });

  test("a malformed queue never breaks the rest of /status", async () => {
    expect(await pollQueue(reply({ ...status, queue: { position: "soon" } }), "http://api"))
      .toEqual({ ok: true, queue: null, service: SERVICE_OK });
  });

  test("the same reply carries the service state", async () => {
    expect(await pollQueue(reply({ ...status, queue: null, service: "paused" }), "http://api"))
      .toEqual({ ok: true, queue: null, service: { status: "paused", retryAfterS: null } });
  });

  test("no usable reply is a failed poll", async () => {
    expect(await pollQueue(async () => { throw new TypeError("network"); }, "http://api"))
      .toEqual({ ok: false });
    expect(await pollQueue(async () => new Response("<html>", { status: 502 }), "http://api"))
      .toEqual({ ok: false });
  });
});

test.describe("readService: tolerant, so anything unknown is ok (Q45)", () => {
  test("paused and daily_limit are read; only daily_limit keeps its seconds", () => {
    expect(readService({ service: "paused", retry_after_s: 60 })).toEqual({ status: "paused", retryAfterS: null });
    expect(readService({ service: "daily_limit", retry_after_s: 7_200 }))
      .toEqual({ status: "daily_limit", retryAfterS: 7_200 });
    expect(readService({ service: "ok" })).toEqual(SERVICE_OK);
  });

  test("an unknown or missing value is ok; a bad wait keeps the limit without seconds", () => {
    for (const raw of [{}, { service: "closed" }, { service: 1 }, null, undefined, "paused", []]) {
      expect(readService(raw), JSON.stringify(raw)).toEqual(SERVICE_OK);
    }
    for (const retry_after_s of [undefined, null, -1, Number.NaN, Infinity, "7200"]) {
      expect(readService({ service: "daily_limit", retry_after_s }), String(retry_after_s))
        .toEqual({ status: "daily_limit", retryAfterS: null });
    }
  });
});

test.describe("wording", () => {
  test("ordinals, including the teens", () => {
    const cases: [number, string][] = [
      [1, "1st"], [2, "2nd"], [3, "3rd"], [4, "4th"], [11, "11th"], [12, "12th"], [13, "13th"],
      [21, "21st"], [22, "22nd"], [23, "23rd"], [99, "99th"], [101, "101st"], [111, "111th"],
      [112, "112th"],
    ];
    for (const [n, text] of cases) expect(ordinal(n)).toBe(text);
  });

  test("waits round up to the next 10 seconds and never show 0", () => {
    const cases: [number, number][] = [[0, 10], [1, 10], [10, 10], [40, 40], [41, 50], [59.5, 60]];
    for (const [seconds, shown] of cases) expect(roundedWait(seconds)).toBe(shown);
  });

  test("the visible line has the seconds, as an upper bound; without an estimate, just the place", () => {
    expect(queuedMessage({ position: 2, waitS: 40 })).toBe("Next in line, up to about 40\u00a0seconds.");
    expect(queuedMessage({ position: 3, waitS: 41 })).toBe("3rd in line, up to about 50\u00a0seconds.");
    expect(queuedMessage({ position: 12, waitS: 5 })).toBe("12th in line, up to about 10\u00a0seconds.");
    expect(queuedMessage({ position: 2, waitS: null })).toBe("Next in line.");
  });

  test("the announcement depends only on the position, never the seconds", () => {
    expect(queuedAnnouncement({ position: 2, waitS: 40 })).toBe("Next in line.");
    expect(queuedAnnouncement({ position: 3, waitS: 40 })).toBe("3rd in line.");
    expect(queuedAnnouncement({ position: 2, waitS: 10 })).toBe(queuedAnnouncement({ position: 2, waitS: 40 }));
    expect(queuedAnnouncement({ position: 3, waitS: 40 })).not.toBe(queuedAnnouncement({ position: 2, waitS: 40 }));
  });

  test("queued means someone is ahead; position 1 reads as loading", () => {
    expect(isQueued(null)).toBe(false);
    expect(isQueued({ position: 1, waitS: 5 })).toBe(false);
    expect(isQueued({ position: 2, waitS: 5 })).toBe(true);
  });
});

test.describe("reducer: queue_update", () => {
  const loading = askReducer(IDLE, {
    type: "submit", repo: "a/b", question: "q?", requestId: 1, at: 1_000, serverUp: true,
  });
  const update = (position: number | null, at: number, requestId = 1): AskEvent => ({
    type: "queue_update", requestId, at,
    queue: position === null ? null : { position, waitS: 30 },
  });
  const run = (events: AskEvent[], from: Ask = loading) => events.reduce(askReducer, from);

  test("a new question starts with no queue", () => {
    expect(loading).toMatchObject({ kind: "loading", queue: null, startedAt: 1_000 });
  });

  test("an update for another request, or when not loading, is dropped", () => {
    expect(run([update(2, 2_000, 99)])).toBe(loading);
    expect(askReducer(IDLE, update(2, 2_000))).toBe(IDLE);
  });

  test("3 -> 2 -> 1: the place is kept, and the escalation clock restarts only on reaching the front", () => {
    let s = run([update(3, 2_000)]);
    expect(s).toMatchObject({ queue: { position: 3 }, startedAt: 1_000 });
    s = askReducer(s, update(2, 5_000));
    expect(s).toMatchObject({ queue: { position: 2 }, startedAt: 1_000 });
    s = askReducer(s, update(1, 8_000));
    expect(s).toMatchObject({ queue: { position: 1 }, startedAt: 8_000 });
  });

  test("a question that never showed a queue keeps its clock at position 1", () => {
    expect(run([update(1, 11_000)])).toMatchObject({ queue: { position: 1 }, startedAt: 1_000 });
    expect(run([update(null, 4_000), update(1, 11_000)])).toMatchObject({ startedAt: 1_000 });
  });
});
