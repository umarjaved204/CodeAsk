// Smoke tests for the e2e setup itself (mentor review, step 2): the production build serves
// the page, the mocks answer, and page.clock can drive the page's timers exactly. The full
// suites build on these. (CORS is not testable through page.route: see mocks.ts.)
import { EXAMPLE, expect, test } from "./mocks";

const LABEL = "Example answer, generated 2 Nov 2026 with qwen3.8-27b on commit 672971d. " +
  "Checked against the cited code by Claude; not yet reviewed by the author.";

test("first screen: the labelled example, with its first valid citation open", async ({ page, api }) => {
  await page.goto("/");
  await expect(page.getByText(LABEL, { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(EXAMPLE.question);
  await expect(page.getByRole("button", { name: "Citation 1: src/itsdangerous/signer.py, lines 67 to 73" }))
    .toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("complementary", { name: "Cited code" })).toContainText("Cited lines 67–73");
  await expect.poll(() => api.count("GET /status")).toBeGreaterThan(0);
});

test("ask -> answer through the mock, as a JSON POST with repo and question", async ({ page, api }) => {
  await page.goto("/");
  await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0); // the server is up
  const sent = page.waitForRequest((r) => r.url().endsWith("/ask") && r.method() === "POST");
  await page.getByLabel("Question").fill("How are signatures verified?");
  await page.getByLabel("Question").press("Enter");
  expect((await sent).postDataJSON())
    .toEqual({ repo: "pallets/itsdangerous", question: "How are signatures verified?" });

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("How are signatures verified?");
  await expect(page.getByText(LABEL)).toHaveCount(0); // a live answer carries no example label
  await expect(page.getByRole("button", { name: /^Citation 1:/ })).toBeVisible();
  await expect(page.getByText("Answer ready.")).toBeAttached();
  expect(api.count("POST /ask")).toBe(1);
});

test("page.clock drives the timers exactly: loading escalates at 12 s, not 11 s", async ({ page, api }) => {
  const t0 = new Date("2026-11-11T10:00:00Z");
  await page.clock.install({ time: t0 });
  api.on("POST /ask", () => new Promise(() => {})); // never answers
  await page.goto("/");
  await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
  // Freeze time, so the submit time and every 1 s tick land on exact values.
  await page.clock.pauseAt(new Date(t0.getTime() + 60_000));

  await page.getByLabel("Question").fill("How are signatures verified?");
  await page.getByLabel("Question").press("Enter");
  await expect(page.getByText("Answering. This usually takes a few seconds.")).toBeVisible();
  await page.clock.runFor(11_000);
  await expect(page.getByText("Answering. This usually takes a few seconds.")).toBeVisible();
  await page.clock.runFor(1_000);
  await expect(page.getByText(/^Still working\./)).toBeVisible();
});
