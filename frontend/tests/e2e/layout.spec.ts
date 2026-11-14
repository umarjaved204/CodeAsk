// Layout boundaries (PLAN.md Q36: side by side from 1024 px, the bottom sheet below) and reflow
// at 320 CSS px (WCAG 1.4.10: no horizontal page scroll, the ask box still usable).
import type { Page } from "@playwright/test";

import { LONG_LINE_END, LONG_LINES, UNGROUNDED, expect, test } from "./mocks";

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

// Round 1, F1: a ~300-character code line widened the panel's grid column, crushing the answer
// at 1024 and making the page scroll sideways at 1440. The e2e suite missed it because no test
// used a long line at these widths.
for (const [width, minReading] of [[1024, 440], [1440, 600]] as const) {
  test(`a long code line scrolls inside the panel at ${width} and never widens the layout`, async ({ page, api }) => {
    await page.setViewportSize({ width, height: 900 });
    api.on("POST /ask", () => ({ json: LONG_LINES }));
    await page.goto("/");
    await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
    await page.getByRole("textbox", { name: "Question" }).fill("How is rotation configured?");
    await page.getByRole("textbox", { name: "Question" }).press("Enter");
    await expect(page.getByText("Answer ready.")).toBeAttached();

    const m = await page.evaluate(() => {
      const box = (el: Element | null) => el?.getBoundingClientRect() ?? new DOMRect();
      const region = document.querySelector<HTMLElement>("aside [role='region']");
      return {
        pageWidth: document.documentElement.scrollWidth, viewport: window.innerWidth,
        reading: box(document.querySelector("section[aria-labelledby='question']")).width,
        panel: box(document.querySelector("aside")),
        answer: box(document.querySelector(".answer")),
        scroll: region ? { width: region.scrollWidth, client: region.clientWidth } : null,
      };
    });
    expect(m.pageWidth).toBeLessThanOrEqual(m.viewport); // 1. no sideways page scroll
    expect(m.reading).toBeGreaterThanOrEqual(minReading); // 2. the reading column keeps its room
    expect(m.reading / (m.reading + m.panel.width)).toBeCloseTo(0.53, 1); // ...and the 53/47 split
    expect(m.answer.right).toBeLessThanOrEqual(m.panel.left); // 3. answer and panel don't overlap
    expect(m.scroll && m.scroll.width > m.scroll.client).toBe(true); // 4. the panel scrolls...

    // ...and scrolling it brings the end of the long line into view: nothing is cut off.
    const region = page.getByRole("complementary", { name: "Cited code" }).getByRole("region");
    await region.evaluate((el) => { el.scrollLeft = el.scrollWidth; });
    const line = region.locator("span.whitespace-pre", { hasText: LONG_LINE_END });
    const [lineBox, regionBox] = await Promise.all([line.boundingBox(), region.boundingBox()]);
    expect(lineBox && regionBox).toBeTruthy();
    expect(lineBox!.x + lineBox!.width).toBeLessThanOrEqual(regionBox!.x + regionBox!.width + 1);
  });
}

// Round 2, R2-2: on a landscape phone the sticky composer took half the height, so the first
// screen showed no answer text. Under 500 px tall it isn't sticky and drops its footer note.
for (const [width, height, short] of [[844, 390, true], [390, 844, false]] as const) {
  test.describe(`${width}x${height}`, () => {
    test.use({ viewport: { width, height }, isMobile: true, hasTouch: true });

    test(short ? "short screen: the answer comes first, the composer isn't sticky"
               : "normal phone (control): the composer stays sticky with its note", async ({ page }) => {
      await page.goto("/");
      await expect(page.getByText(/^Example answer/)).toBeVisible();
      const position = await page.locator("#ask").evaluate((el) => getComputedStyle(el).position);
      expect(position).toBe(short ? "static" : "sticky");
      // The composer's note (Q79 wording); scoped to the form, since the empty state says the
      // same first sentence.
      const note = page.locator("#ask").getByText(/^Answers cite the lines they use\./);
      expect(await note.count()).toBe(1); // present in the DOM, so "hidden" can't pass vacuously
      if (short) {
        await expect(note).toBeHidden();
        await expect(page.locator(".answer p").first()).toBeInViewport();
      } else {
        await expect(note).toBeVisible();
      }
    });
  });
}

// Step 5 (mentor): WCAG 1.4.12 text spacing. With the user-override spacing applied, nothing
// may be clipped, overflow sideways or overlap, on the key states.
const TEXT_SPACING = "* { line-height: 1.5 !important; letter-spacing: 0.12em !important; " +
  "word-spacing: 0.16em !important; } p { margin-bottom: 2em !important; }";

for (const [width, height, withSheet] of [[1440, 900, false], [390, 844, false], [390, 844, true]] as const) {
  test(`text spacing override at ${width}x${height}${withSheet ? ", sheet open" : ""}: nothing clipped or overlapping`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto("/");
    await expect(page.getByText(/^Example answer/)).toBeVisible();
    await page.addStyleTag({ content: TEXT_SPACING });
    if (withSheet) {
      await chip2(page).click();
      await expect(sheet(page)).toBeVisible();
    }
    const problems = await page.evaluate(() => {
      const found: string[] = [];
      const doc = document.documentElement;
      if (doc.scrollWidth > doc.clientWidth) found.push(`page scrolls sideways (${doc.scrollWidth}px)`);
      for (const el of document.querySelectorAll<HTMLElement>("body *")) {
        if (el.closest(".sr-only") || !el.textContent?.trim()) continue;
        const s = getComputedStyle(el);
        const clips = (v: string) => v === "hidden" || v === "clip";
        if (clips(s.overflowX) && el.scrollWidth > el.clientWidth + 1) found.push(`clipped sideways: ${el.tagName}`);
        if (clips(s.overflowY) && el.scrollHeight > el.clientHeight + 1) found.push(`clipped vertically: ${el.tagName}`);
      }
      const box = (sel: string) => document.querySelector(sel)?.getBoundingClientRect();
      const overlap = (a?: DOMRect, b?: DOMRect) =>
        !!a && !!b && a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
      if (overlap(box("#question-box"), box("#ask button[type='submit']"))) found.push("question box overlaps Ask");
      if (overlap(box("#repo"), box("#ask .tabular-nums"))) found.push("repo picker overlaps the counter");
      return found;
    });
    expect(problems).toEqual([]);
  });
}

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

  // Pass 1 of the 3b.7 review (Q80): text with no break opportunity must wrap, not widen the page.
  async function expectNoSidewaysScroll(page: Page, element: ReturnType<Page["locator"]>) {
    const widths = await page.evaluate(() => ({
      page: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth,
    }));
    expect(widths.page).toBeLessThanOrEqual(widths.viewport);
    const box = (await element.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(widths.viewport);
  }

  test("a long unbroken question wraps inside the column", async ({ page, api }) => {
    const question = "https://github.com/pallets/itsdangerous/blob/main/src/itsdangerous/" +
      "a_very_long_module_name_with_no_spaces_at_all_for_the_overflow_check.py";
    await page.goto("/");
    await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
    await page.getByRole("textbox", { name: "Question" }).fill(question);
    await page.getByRole("button", { name: "Ask", exact: true }).tap();
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toHaveText(question);
    await expectNoSidewaysScroll(page, heading);
  });

  test("a long path among an ungrounded answer's closest files wraps inside the column", async ({ page, api }) => {
    const path = "lib/a/deeply/nested/directory/structure/with_a_very_long_file_name_for_overflow.js";
    api.on("POST /ask", () => ({ json: { ...UNGROUNDED, possibly_relevant: [
      { path, start: 1, end: 20, url: `https://github.com/expressjs/express/blob/main/${path}#L1-L20` },
    ] } }));
    await page.goto("/");
    await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
    await page.getByRole("textbox", { name: "Question" }).fill("Where is routing set up?");
    await page.getByRole("button", { name: "Ask", exact: true }).tap();
    const link = page.getByRole("link", { name: `${path}:1-20 (opens in a new tab)`, exact: true });
    await expect(link).toBeVisible();
    await expectNoSidewaysScroll(page, link);
  });
});
