// The page against the real backend's replies (step 8): backend/tests/test_api.py writes them
// to tests/contract/backend-replies.json from the actual app (TestClient), and fails if the
// file is stale. The mocks are hand-written; this is what keeps them honest.
import { expect, test } from "@playwright/test";

import { classify, readQueue, readService } from "../../lib/api";
import { EXPOSED_HEADERS } from "../e2e/mocks";
import replies from "../contract/backend-replies.json";

type Recorded = { status: number; headers: Record<string, string>; body: Record<string, unknown> };
const REPLIES = replies as unknown as Record<string, Recorded>;

function response(r: Recorded): Response {
  return new Response(JSON.stringify(r.body), {
    status: r.status, headers: { "content-type": "application/json", ...r.headers } });
}

const set = (list: string) => new Set(list.split(",").map((h) => h.trim().toLowerCase()));

test("every refusal is a known code with its request id and Retry-After", async () => {
  const refusals = Object.entries(REPLIES).filter(([name]) => name.startsWith("ask "));
  expect(refusals.map(([name]) => name.slice(4)).sort())
    .toEqual(["busy", "daily_limit", "in_progress", "paused", "per_ip_limit"]);
  for (const [name, recorded] of refusals) {
    const result = await classify(response(recorded));
    expect(result.ok, name).toBe(false);
    if (result.ok || result.failure.kind !== "api") throw new Error(`${name}: not an API failure`);
    expect(result.failure.code, name).toBe(recorded.body.error); // known: never the generic "error"
    expect(result.failure.requestId, name).toBe("a1b2c3d4");
    const header = recorded.headers["retry-after"];
    expect(result.failure.retryAfterS, name).toBe(header === undefined ? null : Number(header));
  }
  expect(REPLIES["ask paused"].headers["retry-after"]).toBeUndefined(); // only the 429s have one
});

test("/status replies read as the service and queue the backend meant", () => {
  expect(readService(REPLIES["status ok"].body)).toEqual({ status: "ok", retryAfterS: null });
  expect(readService(REPLIES["status paused"].body)).toEqual({ status: "paused", retryAfterS: null });
  expect(readService(REPLIES["status daily_limit"].body))
    .toEqual({ status: "daily_limit", retryAfterS: REPLIES["status daily_limit"].body.retry_after_s });
  expect(readQueue(REPLIES["status ok"].body.queue)).toBeNull();
  expect(readQueue(REPLIES["status queue"].body.queue)).toEqual({ position: 2, waitS: 0 });
  for (const name of ["status ok", "status queue"]) {
    expect(REPLIES[name].headers["cache-control"], name).toBe("no-store");
  }
});

test("every reply exposes the headers the mocks expose", () => {
  for (const [name, recorded] of Object.entries(REPLIES)) {
    expect(set(recorded.headers["access-control-expose-headers"] ?? ""), name)
      .toEqual(set(EXPOSED_HEADERS));
  }
});
