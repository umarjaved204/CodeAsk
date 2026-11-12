// Slice 4 (PLAN.md Q45, Q46 C7, step 8 decisions): the service line, the four refusals, one
// owner per message, the refresh on return to the tab, and the long line's layout.
//
// "Never both, never neither": in a refusal the composer line would say exactly the same text as
// the question's own status (both end "The suggested questions still work.", the list being on
// screen, Q54), so toHaveCount(1) on that exact text fails if both speak and if neither does.
import type { Page } from "@playwright/test";

import { EXAMPLE, apiError, expect, statusWith, test, type MockApi } from "./mocks";
import {
  IN_PROGRESS_MESSAGE, dailyLimitMessage, pausedMessage, perVisitorMessage,
} from "../../lib/messages";

const Q = "How are signatures verified?";
const LABEL = /^Example answer, generated 2 Nov 2026/;
const T0 = Date.parse("2026-11-11T10:00:00Z");

const box = (page: Page) => page.getByRole("textbox", { name: "Question" });
const askButton = (page: Page) => page.getByRole("button", { name: /^Ask/ });
const exact = (page: Page, text: string) => page.getByText(text, { exact: true });
// The question's own assertive region (Next.js adds a second role=alert: its route announcer).
const alarm = (page: Page) => page.getByRole("region", { name: Q }).getByRole("alert");

async function up(page: Page, api: MockApi) {
  await page.goto("/");
  await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
}

async function ask(page: Page) {
  await box(page).fill(Q);
  await box(page).press("Enter");
}

// ---------- the service line on load ----------
test("paused on load: the composer says so, the example stays, and Ask stays enabled", async ({ page, api }) => {
  api.on("GET /status", () => statusWith(null, "paused"));
  await up(page, api);
  await expect(exact(page, pausedMessage(true))).toBeVisible();
  await expect(page.getByText(LABEL)).toBeVisible();
  await box(page).fill(Q);
  await expect(askButton(page)).toBeEnabled(); // Q46 C7: the server decides, not the page
});

test("a repo without an example: the line drops the example sentence", async ({ page, api }) => {
  api.on("GET /status", () => statusWith(null, "paused"));
  await up(page, api);
  await page.getByRole("combobox", { name: "Repository" }).selectOption("psf/requests");
  await expect(exact(page, pausedMessage(false))).toBeVisible();
  await expect(exact(page, pausedMessage(true))).toHaveCount(0);
});

test("daily limit on load: about N from the reply's retry_after_s", async ({ page, api }) => {
  api.on("GET /status", () => statusWith(null, "daily_limit", 7_200));
  await up(page, api);
  await expect(exact(page, dailyLimitMessage(7_200, true))).toBeVisible(); // "about 2 hours"
});

// ---------- refusals from /ask, one owner per message ----------
test("a paused refusal: said once, under the question; the line returns with the example", async ({ page, api }) => {
  api.on("POST /ask", () => apiError(503, "paused", "Live questions are paused right now."));
  await up(page, api);
  await ask(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(Q);
  await expect(exact(page, pausedMessage(true))).toHaveCount(1); // never both, never neither
  await expect(page.getByRole("button", { name: "Try again", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: EXAMPLE.question, exact: true }).click(); // the way back
  await expect(page.getByText(LABEL)).toBeVisible();
  await expect(exact(page, pausedMessage(true))).toBeVisible(); // derived from state: it's back
});

test("a refusal that changes the service moves the line along, then it goes quiet", async ({ page, api }) => {
  api.on("GET /status", () => statusWith(null, "paused"));
  api.on("POST /ask", () => apiError(429, "daily_limit", "Used up.", { "Retry-After": "7200" }));
  await up(page, api);
  await expect(exact(page, pausedMessage(true))).toBeVisible();
  await ask(page);
  await expect(exact(page, dailyLimitMessage(7_200, true))).toHaveCount(1);
  await expect(page.getByText(/^Live questions are paused/)).toHaveCount(0); // no stale line
});

test("per-visitor limit: a calm 429 with its time, and no retry", async ({ page, api }) => {
  api.on("POST /ask", () => apiError(429, "per_ip_limit", "Limit.", { "Retry-After": "10800" }));
  await up(page, api);
  await ask(page);
  await expect(exact(page, perVisitorMessage(10_800, true))).toHaveCount(1); // "about 3 hours"
  await expect(alarm(page)).toHaveText(""); // calm: the polite region speaks
  await expect(page.getByRole("button", { name: "Try again", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: EXAMPLE.question, exact: true })).toBeVisible();
});

test("previous question in progress: the busy countdown, with its own sentence", async ({ page, api }) => {
  await page.clock.setFixedTime(T0);
  api.on("POST /ask", () => apiError(429, "in_progress", "Still answering.", { "Retry-After": "40" }));
  await up(page, api);
  await ask(page);
  await expect(exact(page, IN_PROGRESS_MESSAGE)).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again in 40 s" })).toBeDisabled();
  await expect(alarm(page)).toHaveText("");
});

// ---------- the refresh on return to the tab (step 8) ----------
test("a stale paused line is refreshed on return to the tab, once a minute at most, never while idle", async ({ page, api }) => {
  await page.clock.install({ time: T0 });
  let service: "ok" | "paused" = "paused";
  api.on("GET /status", () => statusWith(null, service));
  await up(page, api);
  await expect(exact(page, pausedMessage(true))).toBeVisible();
  const returnToTab = () => page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  const polls = api.count("GET /status");

  await page.clock.runFor(30_000);
  await returnToTab(); // under a minute since the last reply: nothing
  await page.clock.runFor(120_000); // idle and visible: nothing either
  expect(api.count("GET /status")).toBe(polls);

  service = "ok"; // the pause was lifted meanwhile
  await returnToTab();
  await expect.poll(() => api.count("GET /status")).toBe(polls + 1);
  await expect(page.getByText(/^Live questions are paused/)).toHaveCount(0);
  await returnToTab(); // open now: no more fetches
  await page.clock.runFor(120_000);
  expect(api.count("GET /status")).toBe(polls + 1);
});

// ---------- the longest line in the sticky composer (pre-registered, step 8) ----------
for (const [width, height] of [[390, 844], [320, 568]] as const) {
  test(`daily limit at ${width}x${height}: the ask box stays fully in view`, async ({ page, api }) => {
    await page.setViewportSize({ width, height });
    api.on("GET /status", () => statusWith(null, "daily_limit", 7_200));
    await up(page, api);
    await expect(exact(page, dailyLimitMessage(7_200, true))).toBeVisible();
    if (width === 390) {
      const composer = await page.locator("#ask").boundingBox();
      expect(composer?.height ?? Infinity).toBeLessThanOrEqual(0.4 * height);
    }
    await expect(box(page)).toBeInViewport({ ratio: 1 });
    await expect(askButton(page)).toBeInViewport({ ratio: 1 });
  });
}
