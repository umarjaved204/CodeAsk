// The mocked API for the browser tests (and, in step 4, the screenshot matrix).
//
// - Every request to the API base goes through a handler table keyed by "METHOD /path". A call
//   with no handler is aborted and fails the test.
// - Any request to a host other than the app itself also fails the test: the page must make no
//   third-party calls (fonts are self-hosted, Q32). data: and blob: URLs are allowed.
// - CORS, measured 2026-11-11 (Playwright 1.64.1, Chromium): a page.route reply with no CORS
//   headers still reaches the page (GET and JSON POST), and the preflight never reaches
//   page.route, so the mocks can't test Access-Control-Allow-Origin. But Chromium still HIDES
//   response headers that aren't exposed: without Access-Control-Expose-Headers the busy test
//   read no Retry-After. So every reply sends the expose list app.py sends, and a missing
//   entry there is pinned by backend/tests/test_api.py. Allow-origin stays a manual check
//   against the real backend.
// - Shapes come from the backend, never from memory: each default names its source.
import { test as base, expect, type Page, type Request } from "@playwright/test";

import { EXAMPLES, FEATURED } from "../../lib/featured";
import type { QueueWire, Status } from "../../lib/types";

export const PORT = 3100;
export const APP_ORIGIN = `http://localhost:${PORT}`;
export const API = "http://api.test";

export const EXAMPLE = EXAMPLES["pallets/itsdangerous"];

export type Reply =
  // expose: false leaves out Access-Control-Expose-Headers (a backend that forgot the list)
  | { status?: number; json: unknown; headers?: Record<string, string>; expose?: boolean }
  | { status: number; body: string; contentType: string } // not our JSON (Render's HTML page)
  | "abort"; // no response at all
export type Handler = (request: Request) => Reply | Promise<Reply>;

// The response headers the page may read. MIRRORS backend/codeask/api/app.py create_app()
// (CORSMiddleware expose_headers), which backend/tests/test_api.py
// test_the_browser_may_read_the_request_id_and_retry_after pins. Change all three together.
export const EXPOSED_HEADERS = "X-Request-Id, Retry-After";

function defaults(): Map<string, Handler> {
  return new Map<string, Handler>([
    // app.py status()
    ["GET /status", () => ({
      json: { ok: true, model: EXAMPLE.model, model_available: true, prompt_version: 3 },
    })],
    // app.py repos()
    ["GET /repos", () => ({
      json: FEATURED.map((r) => ({ ...r, commit_sha: EXAMPLE.commit_sha,
                                   ingested_at: "2026-11-02T00:00:00+00:00" })),
    })],
    // ask.py public_view(), as saved by `ask --save` in the real fixture
    ["POST /ask", () => ({ json: EXAMPLE.response })],
  ]);
}

/** A reply the test sends when it chooses: for loading states and races. */
export function held() {
  let release!: (reply: Reply) => void;
  const reply = new Promise<Reply>((resolve) => { release = resolve; });
  return { handler: () => reply, release };
}

/** app.py error_json(): ApiError's status and headers, body {error, message, request_id}. */
export function apiError(status: number, code: string, message: string,
                         headers?: Record<string, string>): Reply {
  return { status, json: { error: code, message, request_id: "a1b2c3d4" }, headers };
}

/** PROVISIONAL (Q40; slice 4 confirms the shape): a /status reply carrying the caller's place
 *  in the /ask queue, as app.py status() is expected to send it. */
export function statusWith(queue: QueueWire | null): Reply {
  const body: Status = { ok: true, model: EXAMPLE.model, model_available: true, prompt_version: 3, queue };
  return { json: body };
}

/** What Render serves while the instance wakes (M2-0): HTML, not our JSON. */
export const NOT_OUR_JSON: Reply = { status: 502, body: "<html>Bad gateway</html>",
                                     contentType: "text/html" };

// ---------- /ask variants, each shaped like ask.py public_view() ----------
const R = EXAMPLE.response;
const PERMALINK = `https://github.com/pallets/itsdangerous/blob/${EXAMPLE.commit_sha}`;

/** Citation 1 unverified. As in evidence(): no url or block, and block 0 (which only citation 1
 *  used) is not sent, so the other citations' block indices shift down by one. */
export const FIRST_UNVERIFIED = {
  ...R,
  blocks: R.blocks.slice(1),
  citations: R.citations.map((c) => c.n === 1
    ? { ...c, valid: false, url: null, block: null }
    : { ...c, block: (c.block ?? 0) - 1 }),
};

/** No valid citation (Q23): text, citations and blocks withheld; answer.py possibly_relevant(). */
export const UNGROUNDED = {
  grounded: false, answer: null, citations: [], blocks: [],
  possibly_relevant: [
    { path: "src/itsdangerous/signer.py", start: 227, end: 242,
      url: `${PERMALINK}/src/itsdangerous/signer.py#L227-L242` },
    { path: "src/itsdangerous/serializer.py", start: 190, end: 241,
      url: `${PERMALINK}/src/itsdangerous/serializer.py#L190-L241` },
    { path: "src/itsdangerous/timed.py", start: 1, end: 30,
      url: `${PERMALINK}/src/itsdangerous/timed.py#L1-L30` },
  ],
  model: R.model, prompt_version: R.prompt_version,
};

/** A 400-line block cited near its end (350-352): more lines than the old 300-line cap, which
 *  hid exactly this case (removed 2026-11-11, "no cited line is ever hidden"). */
export const LONG_BLOCK = {
  ...R,
  answer: "The long block [1](cite:1).",
  citations: [{ n: 1, path: "src/long.py", start: 350, end: 352, valid: true,
                url: `${PERMALINK}/src/long.py#L350-L352`, block: 0 }],
  blocks: [{ path: "src/long.py", start: 1, end: 400,
             content: Array.from({ length: 400 }, (_, i) => `line ${i + 1}`).join("\n") }],
};

/** Code lines wider than the panel, one of them ~300 characters (screens state 13, and the
 *  round 1 F1 regression: a long line must scroll inside the panel, never widen the layout). */
export const LONG_LINE_END = "until their old key is removed";
export const LONG_LINES = {
  ...R,
  answer: "Rotation is configured in one call, with the old and the new key side by side [1](cite:1).",
  citations: [{ n: 1, path: "examples/rotation_config.py", start: 3, end: 6, valid: true, block: 0,
                url: `${PERMALINK}/examples/rotation_config.py#L3-L6` }],
  blocks: [{
    path: "examples/rotation_config.py", start: 1, end: 8,
    content: [
      "def make_signer(app):",
      "    \"\"\"Sign with the newest key; verify with every key still listed.\"\"\"",
      "    return Signer(",
      "        secret_key=[\"2025-key-kept-for-tokens-issued-before-the-rotation\", \"2026-current-key\"], salt=\"itsdangerous.Signer\", key_derivation=\"django-concat\", digest_method=hashlib.sha256,",
      "    # rotation: append new keys at the end, keep old keys until every token they signed " +
      "has expired, then remove them from the start of the list; signing always uses the last " +
      "key, verification tries every key from newest to oldest, so tokens issued before the " +
      `rotation keep working ${LONG_LINE_END}`,
      "    )",
      "",
      "# The list order is the contract: oldest first, newest last.",
    ].join("\n"),
  }],
};

export class MockApi {
  private readonly handlers = defaults();
  private readonly counts = new Map<string, number>();
  readonly unexpected: string[] = [];

  /** Replace the handler for "METHOD /path", e.g. on("POST /ask", ...). */
  on(key: string, handler: Handler) {
    this.handlers.set(key, handler);
  }

  count(key: string): number {
    return this.counts.get(key) ?? 0;
  }

  async install(page: Page) {
    await page.route(`${API}/**`, async (route) => {
      const request = route.request();
      const key = `${request.method()} ${new URL(request.url()).pathname}`;
      const handler = this.handlers.get(key);
      if (!handler) {
        this.unexpected.push(key);
        return route.abort();
      }
      this.counts.set(key, this.count(key) + 1);
      const reply = await handler(request);
      try {
        if (reply === "abort") return await route.abort("connectionrefused");
        if ("body" in reply) {
          return await route.fulfill({ status: reply.status, contentType: reply.contentType,
                                       body: reply.body });
        }
        return await route.fulfill({
          status: reply.status ?? 200, contentType: "application/json",
          body: JSON.stringify(reply.json),
          headers: { ...(reply.expose === false ? {} : { "access-control-expose-headers": EXPOSED_HEADERS }),
                     ...reply.headers },
        });
      } catch {
        // The page already gave up on this request (e.g. a /status poll aborted when the
        // question settled, Q40). A held reply released afterwards has nowhere to go.
      }
    });
  }
}

export const test = base.extend<{ api: MockApi }>({
  api: [async ({ page, context }, use) => {
    const offsite: string[] = [];
    // Page routes take precedence, so this only sees what the API mock doesn't handle.
    await context.route(() => true, (route) => {
      const url = route.request().url();
      if (url.startsWith(`${APP_ORIGIN}/`) || /^(data|blob):/.test(url)) return route.continue();
      offsite.push(url);
      return route.abort();
    });
    const api = new MockApi();
    await api.install(page);
    await use(api);
    expect(api.unexpected, "API calls with no mock").toEqual([]);
    expect(offsite, "requests to other hosts").toEqual([]);
  }, { auto: true }],
});

export { expect };
