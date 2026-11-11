// Layout boundaries (PLAN.md Q36: side by side from 1024 px, the bottom sheet below) and reflow
// at 320 CSS px (WCAG 1.4.10: no horizontal page scroll, the ask box still usable).
import type { Page } from "@playwright/test";

import { expect, test } from "./mocks";

const panel = (page: Page) => page.getByRole("complementary", { name: "Cited code" });
const sheet = (page: Page) => page.getByRole("dialog", { name: "Cited code" });
const chip2 = (page: Page) => page.getByRole("button", { name: /^Citation 2:/ });

test("1023 px: no side panel; a chip opens the sheet", async ({ page }) => {
  await page.setViewportSize({ width: 1023, height: 900 });
  await page.goto("/");
  await expect(panel(page)).toBeHidden();
  await chip2(page).click();
  await expect(sheet(page)).toBeVisible();
  await expect(sheet(page)).toContainText("Cited lines 138–142");
});

test("1024 px: the side panel; a chip updates it and no sheet opens", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 900 });
  await page.goto("/");
  await expect(panel(page)).toBeVisible();
  await chip2(page).click();
  await expect(panel(page)).toContainText("Cited lines 138–142");
  await expect(sheet(page)).toBeHidden();
});

test.describe("reflow at 320x568", () => {
  test.use({ viewport: { width: 320, height: 568 }, isMobile: true, hasTouch: true });

  test("no horizontal page scroll, and the ask box works", async ({ page, api }) => {
    await page.goto("/");
    await expect(page.getByText(/^Example answer/)).toBeVisible();
    const widths = await page.evaluate(() => ({
      page: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth,
    }));
    expect(widths.page).toBeLessThanOrEqual(widths.viewport);

    await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
    const box = page.getByRole("textbox", { name: "Question" });
    await expect(box).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeInViewport({ ratio: 1 });
    await box.fill("How are signatures verified?");
    await page.getByRole("button", { name: "Ask", exact: true }).tap();
    await expect.poll(() => api.count("POST /ask")).toBe(1);
  });
});
