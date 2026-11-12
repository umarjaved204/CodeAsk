// The suggested questions (PLAN.md slice 5, Q54, step 8). Only itsdangerous q1 is stored before
// generation (step 11), so the cases that need two stored answers or a second exported repo
// (rapid picks between answers, A -> B -> C switches, a failed chunk) are added once they exist.
import type { Page } from "@playwright/test";

import { EXAMPLE, expect, held, test, type MockApi } from "./mocks";
import { ON_ITS_OWN } from "../../lib/messages";

const Q = "How are signatures verified?";
const LABEL = /^Example answer, generated 2 Nov 2026/;
const box = (page: Page) => page.getByRole("textbox", { name: "Question" });
const list = (page: Page) => page.getByRole("region", { name: "Suggested questions" });
const item = (page: Page) => list(page).getByRole("button", { name: EXAMPLE.question, exact: true });
const heading = (page: Page) => page.getByRole("heading", { level: 1 });

async function up(page: Page, api: MockApi) {
  await page.goto("/");
  await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
}

async function ask(page: Page, question = Q) {
  await box(page).fill(question);
  await box(page).press("Enter");
}

test("the page opens on the flagship, marked current in the list", async ({ page, api }) => {
  await up(page, api);
  await expect(heading(page)).toHaveText(EXAMPLE.question);
  await expect(page.getByText(LABEL)).toBeVisible();
  await expect(item(page)).toHaveAttribute("aria-current", "true");
  await expect(page.getByText(ON_ITS_OWN)).toHaveCount(0); // the note is for live answers
});

test("under a live answer: the note, the list, nothing marked current", async ({ page, api }) => {
  await up(page, api);
  await ask(page);
  await expect(heading(page)).toHaveText(Q);
  await expect(page.getByText(ON_ITS_OWN)).toBeVisible();
  await expect(item(page)).toBeVisible();
  await expect(item(page)).not.toHaveAttribute("aria-current", /.*/);
});

test("a pick shows the stored answer at once: no request, focus on the question, draft kept", async ({ page, api }) => {
  await up(page, api);
  await ask(page);
  await expect(heading(page)).toHaveText(Q);
  await box(page).fill("a draft I haven't sent");
  const asks = api.count("POST /ask");
  await item(page).click();
  await expect(heading(page)).toHaveText(EXAMPLE.question);
  await expect(page.getByText(LABEL)).toBeVisible();
  await expect(heading(page)).toBeFocused();
  await expect(item(page)).toHaveAttribute("aria-current", "true");
  await expect(box(page)).toHaveValue("a draft I haven't sent");
  expect(api.count("POST /ask")).toBe(asks);
});

test("the list is hidden while a question loads", async ({ page, api }) => {
  const reply = held();
  api.on("POST /ask", reply.handler);
  await up(page, api);
  await ask(page);
  await expect(page.getByText(/^Answering\./)).toBeVisible();
  await expect(list(page)).toHaveCount(0);
  reply.release({ json: EXAMPLE.response });
  await expect(item(page)).toBeVisible();
});

test("a typed question that matches a suggestion still goes live", async ({ page, api }) => {
  await up(page, api);
  await ask(page, EXAMPLE.question);
  await expect.poll(() => api.count("POST /ask")).toBe(1);
  await expect(page.getByText(ON_ITS_OWN)).toBeVisible();
  await expect(item(page)).not.toHaveAttribute("aria-current", /.*/);
});

test("a repo with no stored set: no stored answer and no list, the composer only", async ({ page, api }) => {
  await up(page, api);
  await page.getByRole("combobox", { name: "Repository" }).selectOption("psf/requests");
  await expect(heading(page)).toHaveText("Ask a question about the code in psf/requests.");
  await expect(list(page)).toHaveCount(0);
  await expect(page.getByText(LABEL)).toHaveCount(0);
  await expect(box(page)).toBeEnabled();
});
