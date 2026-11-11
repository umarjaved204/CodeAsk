// The mobile bottom sheet (PLAN.md state inventory 1 and 15, Q34: a native <dialog> with
// showModal()). Phone emulation, not just a narrow viewport: touch taps and a mobile UA.
// Below 1024 px (Q36) there is no side panel, so evidence lives only in the sheet.
import type { Page } from "@playwright/test";

import { expect, test } from "./mocks";

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

const sheet = (page: Page) => page.getByRole("dialog", { name: "Cited code" });
const chip2 = (page: Page) => page.getByRole("button", { name: /^Citation 2:/ });

async function focusInsideSheet(page: Page): Promise<boolean> {
  return page.evaluate(() => !!document.querySelector("dialog")?.contains(document.activeElement));
}

const htmlOverflow = (page: Page) =>
  page.evaluate(() => getComputedStyle(document.documentElement).overflow);

test("first screen: no side panel, the sheet closed, and the tap hint shown", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/^Example answer/)).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Cited code" })).toBeHidden();
  await expect(sheet(page)).toBeHidden(); // nothing opens on its own
  await expect(page.getByText("Tap a citation to see the code.")).toBeVisible();
});

test("a tapped chip opens the sheet on its lines; Esc closes it and focus returns to the chip", async ({ page }) => {
  await page.goto("/");
  await chip2(page).tap();
  await expect(sheet(page)).toBeVisible();
  await expect(sheet(page)).toContainText("Cited lines 138–142, shown within 129–213");
  expect(await focusInsideSheet(page)).toBe(true);
  expect(await htmlOverflow(page)).toBe("hidden"); // the page behind doesn't scroll

  await page.keyboard.press("Escape");
  await expect(sheet(page)).toBeHidden();
  await expect(chip2(page)).toBeFocused();
  expect(await htmlOverflow(page)).not.toBe("hidden");

  await page.keyboard.press("Enter"); // the focused chip reopens it
  await expect(sheet(page)).toBeVisible();
});

test("Close closes the sheet and focus returns to the chip", async ({ page }) => {
  await page.goto("/");
  await chip2(page).tap();
  await expect(sheet(page)).toBeVisible();
  await sheet(page).getByRole("button", { name: "Close" }).tap();
  await expect(sheet(page)).toBeHidden();
  await expect(chip2(page)).toBeFocused();
});

// The requirement: a keyboard user can never reach the page behind the open sheet. A native
// modal <dialog> makes that page inert; after the sheet's last control, Chrome lets Tab move to
// the browser's own UI (seen from the page as focus on <body>), then back into the sheet.
test("while the sheet is open, Tab never reaches the page behind it", async ({ page }) => {
  await page.goto("/");
  await chip2(page).tap();
  await expect(sheet(page)).toBeVisible();
  // Close, View on GitHub, the code region and 7 list items: 12 presses go past the end.
  const where: string[] = [];
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    where.push(await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return "outside the page";
      return document.querySelector("dialog")?.contains(el) ? "sheet" : `BEHIND: ${el.outerHTML.slice(0, 80)}`;
    }));
  }
  console.log(`focus after each Tab: ${where.join(", ")}`);
  expect(where.filter((w) => w.startsWith("BEHIND"))).toEqual([]);
  expect(where.lastIndexOf("sheet")).toBeGreaterThan(where.indexOf("outside the page")); // it comes back
});

test("a tap on the dimmed area closes the sheet; taps and Enter inside it don't", async ({ page }) => {
  await page.goto("/");
  await chip2(page).tap();
  await expect(sheet(page)).toBeVisible();

  // Controls: a tap on the sheet's own text, and Enter on a list item inside, keep it open.
  await sheet(page).getByText("Cited lines 138–142, shown within 129–213").tap();
  const third = sheet(page).getByRole("button", { name: /signer\.py, lines 175–180/ });
  await third.focus();
  await page.keyboard.press("Enter");
  await expect(sheet(page)).toContainText("Cited lines 175–180");
  await expect(sheet(page)).toBeVisible();

  // The backdrop: above the sheet, which covers the bottom 80% of the screen.
  const box = await sheet(page).boundingBox();
  await page.touchscreen.tap(195, (box?.y ?? 200) / 2);
  await expect(sheet(page)).toBeHidden();
  await expect(chip2(page)).toBeFocused();
});

test("another citation chosen inside the sheet replaces the lines in place", async ({ page }) => {
  await page.goto("/");
  await chip2(page).tap();
  await sheet(page).getByRole("button", { name: /signer\.py, lines 175–180/ }).tap();
  await expect(sheet(page)).toContainText("Cited lines 175–180");
  await expect(sheet(page)).toBeVisible();
});
