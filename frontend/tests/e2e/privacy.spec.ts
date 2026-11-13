// Slice 6 step 3b.5 (PLAN.md Q78): the header's links, the composer's privacy sentence and the
// /privacy page, every word from PRIVACY in lib/messages.ts. Axe on /privacy in both themes is
// a state in a11y.spec.ts.
import type { Locator, Page } from "@playwright/test";

import { expect, test, type MockApi } from "./mocks";
import { PRIVACY, privacyLastChecked } from "../../lib/messages";

const NEW_TAB = " (opens in a new tab)";
// The sentence the privacy sentence replaced: the note must not grow past it (Q78).
const OLD_NOTE = "Answers use only the code of the featured repos and cite the lines they rely on. " +
  "Rate-limited demo; each question is answered on its own.";

const banner = (page: Page) => page.getByRole("banner");
const box = (page: Page) => page.getByRole("textbox", { name: "Question" });

async function up(page: Page, api: MockApi) {
  await page.goto("/");
  await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
}

async function expectNewTab(link: Locator, href: string) {
  await expect(link).toHaveAttribute("href", href);
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");
}

for (const [width, height] of [[320, 568], [390, 844], [1440, 900]] as const) {
  test.describe(`${width}x${height}`, () => {
    test.use({ viewport: { width, height } });

    test("the header fits: brand, both links and the toggle on one row, no sideways scroll", async ({ page, api }) => {
      await up(page, api);
      const items = [
        banner(page).getByText("CodeAsk", { exact: true }),
        banner(page).getByRole("link", { name: `How it works${NEW_TAB}` }),
        banner(page).getByRole("link", { name: `Privacy${NEW_TAB}` }),
        banner(page).getByRole("button", { name: /^Switch to/ }),
      ];
      const boxes: { x: number; y: number; width: number; height: number }[] = [];
      for (const item of items) {
        await expect(item).toBeInViewport({ ratio: 1 });
        boxes.push((await item.boundingBox())!);
      }
      for (let i = 1; i < boxes.length; i++) {
        expect(boxes[i].x, "no overlap with the item before").toBeGreaterThanOrEqual(boxes[i - 1].x + boxes[i - 1].width);
        expect(Math.abs((boxes[i].y + boxes[i].height / 2) - (boxes[0].y + boxes[0].height / 2)))
          .toBeLessThanOrEqual(2); // one row
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth))
        .toBeLessThanOrEqual(width);
    });

    test("the composer's privacy sentence takes no more lines than the sentence it replaced", async ({ page, api }) => {
      await up(page, api);
      const note = page.getByText(PRIVACY.short);
      await expect(note).toBeVisible();
      const [now, before] = await note.evaluate((p, old) => {
        const clone = p.cloneNode(false) as HTMLElement;
        clone.textContent = old;
        p.after(clone);
        const heights = [p.getBoundingClientRect().height, clone.getBoundingClientRect().height];
        clone.remove();
        return heights;
      }, OLD_NOTE);
      expect(now).toBeLessThanOrEqual(before);
    });
  });
}

test("both header links and the composer's link open in a new tab; the draft stays", async ({ page, api }) => {
  await up(page, api);
  await expectNewTab(banner(page).getByRole("link", { name: `How it works${NEW_TAB}` }),
                     "https://github.com/umarjaved204/codeask#readme");
  const privacy = banner(page).getByRole("link", { name: `Privacy${NEW_TAB}` });
  await expectNewTab(privacy, "/privacy");
  await expectNewTab(page.locator("#ask").getByRole("link", { name: `Privacy${NEW_TAB}` }), "/privacy");

  await box(page).fill("a draft I haven't sent");
  const [tab] = await Promise.all([page.waitForEvent("popup"), privacy.click()]);
  await expect(tab.getByRole("heading", { level: 1, name: "Privacy" })).toBeVisible();
  expect(new URL(tab.url()).pathname).toBe("/privacy");
  await expect(box(page)).toHaveValue("a draft I haven't sent");
});

test("/privacy shows exactly the PRIVACY text, its links in new tabs, and the date", async ({ page }) => {
  const response = await page.goto("/privacy");
  expect(response!.status()).toBe(200);
  await expect(page).toHaveTitle("Privacy · CodeAsk");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { level: 1 })).toHaveText("Privacy");
  await expect(main.getByText(PRIVACY.summary, { exact: true })).toBeVisible();
  await expect(main.getByRole("heading", { level: 2 })).toHaveText(
    [...PRIVACY.sections.map((s) => s.heading), "Their policies"]);
  for (const section of PRIVACY.sections) {
    for (const text of section.paragraphs) {
      await expect(main.getByText(text, { exact: true })).toBeVisible();
    }
  }
  for (const link of [...PRIVACY.links, { label: PRIVACY.contact.text, href: PRIVACY.contact.href }]) {
    await expectNewTab(main.getByRole("link", { name: `${link.label}${NEW_TAB}` }), link.href);
  }
  await expect(main.getByText(privacyLastChecked(), { exact: true })).toBeVisible();
  await expect(main.getByRole("link", { name: "Back to CodeAsk" })).toHaveAttribute("href", "/");
  // The header keeps "How it works" and the theme toggle, with no link to the page itself.
  await expect(banner(page).getByRole("link", { name: `How it works${NEW_TAB}` })).toBeVisible();
  await expect(banner(page).getByRole("link", { name: /^Privacy/ })).toHaveCount(0);
});
