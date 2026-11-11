// Injection render tests (PLAN.md Q17, Q18, Q34 step 6). Model text and server URLs are data:
// nothing in them may execute, become a link or an image, or load anything. Every case has a
// POSITIVE CONTROL (the payload is visible as text, and a real citation chip in the same answer
// works), so "nothing executed" can't pass just because nothing rendered. The mocks' offsite
// guard also fails the test if anything requests evil.example.
import type { Page } from "@playwright/test";

import { EXAMPLE, expect, test } from "./mocks";

const R = EXAMPLE.response;
const CHIP_1 = "Citation 1: src/itsdangerous/signer.py, lines 67 to 73";

const PAYLOAD = [
  "Signatures use the key list [1](cite:1).", // the positive control: a real chip
  "<script>window.__pwned = 'script'</script>",
  "A <img src=x onerror=\"window.__pwned = 'img'\"> B",
  "[js link](javascript:window.__pwned='link') and [mixed case](JaVaScRiPt:window.__pwned='mixed')",
  "[plain link](https://evil.example/a) and <https://evil.example/b>",
  "![an image](https://evil.example/i.png) after-image",
  "Bad markers [zero](cite:0) [suffix](cite:12abc) [missing](cite:99).",
].join("\n\n");

/** Visible text each payload must leave behind. */
const SHOWN_AS_TEXT = [
  "<script>window.__pwned = 'script'</script>",
  "A <img src=x onerror=\"window.__pwned = 'img'\"> B",
  "js link and mixed case",
  "plain link and https://evil.example/b",
  "after-image",
  "Bad markers zero suffix missing.",
];

function pageErrors(page: Page): Error[] {
  const errors: Error[] = [];
  page.on("pageerror", (error) => errors.push(error));
  return errors;
}

const pwned = (page: Page) =>
  page.evaluate(() => (window as unknown as { __pwned?: string }).__pwned);

async function askAndWait(page: Page, question: string) {
  const box = page.getByRole("textbox", { name: "Question" });
  await box.fill(question);
  await box.press("Enter");
  await expect(page.getByText("Answer ready.")).toBeAttached();
}

test("an answer full of injection payloads renders them as inert text", async ({ page, api }) => {
  const errors = pageErrors(page);
  api.on("POST /ask", () => ({
    json: { ...R, answer: PAYLOAD, citations: [R.citations[0]], blocks: [R.blocks[0]] },
  }));
  await page.goto("/");
  await askAndWait(page, "What does this answer contain?");

  const answer = page.locator(".answer");
  for (const text of SHOWN_AS_TEXT) await expect(answer).toContainText(text); // it rendered
  await expect(answer.locator("script, img, iframe, a")).toHaveCount(0);
  await expect(page.locator("a[href^='javascript' i], a[href*='evil.example']")).toHaveCount(0);
  // The bad cite: markers are plain text; only the real citation is a chip, and it works.
  await expect(answer.getByRole("button")).toHaveCount(1);
  await answer.getByRole("button", { name: CHIP_1 }).click();
  await expect(page.getByRole("complementary", { name: "Cited code" })).toContainText("Cited lines 67–73");

  expect(await pwned(page)).toBeUndefined();
  expect(errors).toEqual([]);
});

test("a question with markup is shown as text in the heading", async ({ page, api }) => {
  const errors = pageErrors(page);
  const question = "<img src=x onerror=\"window.__pwned = 'question'\"> how?";
  await page.goto("/");
  await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
  await askAndWait(page, question);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(question);
  await expect(page.locator("h1 img")).toHaveCount(0);
  expect(await pwned(page)).toBeUndefined();
  expect(errors).toEqual([]);
});

test("server URLs that aren't https://github.com/ never become links", async ({ page, api }) => {
  const errors = pageErrors(page);
  const lookalike = "https://github.com.evil.example/o/r#L67-L73";
  api.on("POST /ask", () => ({
    json: { ...R, citations: R.citations.map((c) => c.n === 1 ? { ...c, url: lookalike } : c) },
  }));
  await page.goto("/");
  await askAndWait(page, "How are signatures verified?");
  const panel = page.getByRole("complementary", { name: "Cited code" });
  await expect(panel).toContainText("Cited lines 67–73"); // the evidence still shows
  await expect(panel.getByRole("link", { name: "View on GitHub" })).toHaveCount(0);
  await page.getByRole("button", { name: /^Citation 2:/ }).click(); // control: a good URL links
  await expect(panel.getByRole("link", { name: "View on GitHub" })).toHaveAttribute("href", R.citations[1].url!);
  expect(errors).toEqual([]);
});

test("an ungrounded reply's file suggestions link only to GitHub", async ({ page, api }) => {
  const sha = EXAMPLE.commit_sha;
  api.on("POST /ask", () => ({
    json: {
      grounded: false, answer: null, citations: [], blocks: [], model: R.model,
      prompt_version: R.prompt_version,
      possibly_relevant: [
        { path: "src/bad.py", start: 1, end: 2, url: "javascript:window.__pwned='file'" },
        { path: "src/good.py", start: 3, end: 4,
          url: `https://github.com/pallets/itsdangerous/blob/${sha}/src/good.py#L3-L4` },
      ],
    },
  }));
  await page.goto("/");
  await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
  const box = page.getByRole("textbox", { name: "Question" });
  await box.fill("Anything?");
  await box.press("Enter");
  await expect(page.getByRole("heading", { name: "No cited answer for this question" })).toBeVisible();
  await expect(page.getByText("src/bad.py:1-2")).toBeVisible(); // shown, as text
  await expect(page.getByRole("link", { name: "src/bad.py:1-2" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "src/good.py:3-4" })).toBeVisible(); // control
  expect(await pwned(page)).toBeUndefined();
});
