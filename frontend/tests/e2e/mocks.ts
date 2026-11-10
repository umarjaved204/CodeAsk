// The mocked API for the browser tests (and, in step 4, the screenshot matrix).
//
// - Every request to the API base goes through a handler table keyed by "METHOD /path". A call
//   with no handler is aborted and fails the test.
// - Any request to a host other than the app itself also fails the test: the page must make no
//   third-party calls (fonts are self-hosted, Q32). data: and blob: URLs are allowed.
// - These mocks say NOTHING about CORS. Measured 2026-11-11 (Playwright 1.64.1, Chromium): a
//   page.route reply with no CORS headers still reaches the page, for a GET and for a JSON POST,
//   and the preflight never reaches page.route. So CORS and the exposed headers (X-Request-Id,
//   Retry-After) are checked only by hand against the real backend, with a forced server error.
// - Shapes come from the backend, never from memory: each default names its source.
import { test as base, expect, type Page, type Request } from "@playwright/test";

import { EXAMPLES, FEATURED } from "../../lib/featured";

export const PORT = 3100;
export const APP_ORIGIN = `http://localhost:${PORT}`;
export const API = "http://api.test";

export const EXAMPLE = EXAMPLES["pallets/itsdangerous"];

export type Reply =
  | { status?: number; json: unknown; headers?: Record<string, string> }
  | { status: number; body: string; contentType: string } // not our JSON (Render's HTML page)
  | "abort"; // no response at all
export type Handler = (request: Request) => Reply | Promise<Reply>;

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
      if (reply === "abort") return route.abort("connectionrefused");
      if ("body" in reply) {
        return route.fulfill({ status: reply.status, contentType: reply.contentType,
                               body: reply.body });
      }
      return route.fulfill({
        status: reply.status ?? 200, contentType: "application/json",
        body: JSON.stringify(reply.json), headers: reply.headers,
      });
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
