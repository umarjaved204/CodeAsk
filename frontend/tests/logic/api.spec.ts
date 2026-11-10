import { expect, test } from "@playwright/test";

import { classify, postAsk } from "../../lib/api";

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json", ...headers } });
}

test("a 200 JSON answer is data", async () => {
  expect(await classify(json(200, { grounded: true }))).toEqual({ ok: true, data: { grounded: true } });
});

test("the API's JSON error becomes a typed failure with Retry-After", async () => {
  const result = await classify(json(503, { error: "busy", message: "The service is busy.",
                                            request_id: "a1b2c3d4" }, { "retry-after": "13" }));
  expect(result).toEqual({ ok: false, failure: {
    kind: "api", status: 503, code: "busy", message: "The service is busy.",
    requestId: "a1b2c3d4", retryAfterS: 13 } });
});

test("an unknown error code is kept generic, and a bad Retry-After is ignored", async () => {
  const result = await classify(json(500, { error: "surprise", message: 7 },
                                     { "retry-after": "Wed, 21 Oct 2026 07:28:00 GMT" }));
  expect(result).toEqual({ ok: false, failure: {
    kind: "api", status: 500, code: "error", message: "", requestId: null, retryAfterS: null } });
});

test("a non-JSON reply (Render's HTML while waking) is unreachable, whatever the status", async () => {
  for (const status of [200, 502, 503]) {
    const html = new Response("<html>waking</html>", {
      status, headers: { "content-type": "text/html" } });
    expect(await classify(html)).toEqual({ ok: false, failure: { kind: "unreachable" } });
  }
});

test("a JSON content type with a broken body is unreachable", async () => {
  const broken = new Response("{not json", { status: 200,
                                             headers: { "content-type": "application/json" } });
  expect(await classify(broken)).toEqual({ ok: false, failure: { kind: "unreachable" } });
});

test("a fetch that throws (no network, CORS-less error) is unreachable", async () => {
  const failing = (async () => { throw new TypeError("Failed to fetch"); }) as typeof fetch;
  expect(await postAsk(failing, "http://api", "a/b", "q?"))
    .toEqual({ ok: false, failure: { kind: "unreachable" } });
});

test("ask is a JSON POST to /ask with the repo and question", async () => {
  const calls: [string, RequestInit | undefined][] = [];
  const recording = (async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    return json(200, { grounded: true });
  }) as typeof fetch;
  await postAsk(recording, "http://api", "a/b", "q?");
  expect(calls[0][0]).toBe("http://api/ask");
  expect(calls[0][1]).toMatchObject({ method: "POST", body: JSON.stringify({ repo: "a/b",
                                                                           question: "q?" }) });
});
