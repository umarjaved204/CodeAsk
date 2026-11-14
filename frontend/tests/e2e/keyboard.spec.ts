// Keyboard, focus, motion, theme and layout checks (PLAN.md slice 3 steps 6 and Done-when).
// Keyboard tests move only with Tab and Enter; each control reached is checked for the visible
// focus outline from globals.css (:focus-visible, 2px solid).
import type { Locator, Page } from "@playwright/test";

import { EXAMPLE, expect, held, test, type MockApi } from "./mocks";

const Q = "How are signatures verified?";

async function serverUp(api: MockApi) {
  await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
}

/** Press Tab until `target` has focus, like a keyboard user would. */
async function tabTo(page: Page, target: Locator, max = 60) {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((el) => el === document.activeElement)) return;
  }
  throw new Error(`not reachable with Tab in ${max} presses`);
}

async function expectVisibleFocus(target: Locator) {
  await expect(target).toBeFocused();
  const outline = await target.evaluate((el) => {
    const style = getComputedStyle(el);
    return `${style.outlineStyle} ${style.outlineWidth}`;
  });
  expect(outline).toBe("solid 2px");
}

const box = (page: Page) => page.getByRole("textbox", { name: "Question" });
const panel = (page: Page) => page.getByRole("complementary", { name: "Cited code" });

test("keyboard only: skip link -> question box -> ask -> chip -> evidence, focus always visible", async ({ page, api }) => {
  await page.goto("/");
  await serverUp(api);

  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to the question box" });
  await expectVisibleFocus(skip);
  await expect(skip).toBeInViewport(); // it shows itself when focused
  await page.keyboard.press("Enter");
  await expectVisibleFocus(box(page));

  await page.keyboard.type(Q);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(Q);

  const chip = page.getByRole("button", { name: /^Citation 2:/ });
  await tabTo(page, chip);
  await expectVisibleFocus(chip);
  await page.keyboard.press("Enter");
  await expect(panel(page)).toContainText("Cited lines 138–142");

  // The panel's own citation list works from the keyboard too.
  const third = panel(page).getByRole("button", { name: /signer\.py, lines 175–180/ });
  await tabTo(page, third);
  await expectVisibleFocus(third);
  await page.keyboard.press("Enter");
  await expect(panel(page)).toContainText("Cited lines 175–180");
});

// Step 5, W1 (WCAG 2.2 SC 2.4.11, which axe doesn't check): a focused chip low in the answer
// must never sit under the sticky composer. Tab only, from the top, to the example's last chip.
for (const [width, height] of [[1440, 900], [390, 844], [320, 568]] as const) {
  test(`focus is never hidden under the sticky composer at ${width}x${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto("/");
    const last = page.locator('.answer button[aria-label^="Citation 7:"]');
    await tabTo(page, last);
    const [chip, composer] = await Promise.all([last.boundingBox(), page.locator("#ask").boundingBox()]);
    expect(chip && composer).toBeTruthy();
    expect(chip!.y + chip!.height).toBeLessThanOrEqual(composer!.y);
    expect(chip!.y).toBeGreaterThanOrEqual(0);
  });
}

// Step 5 (mentor): Enter that confirms an IME composition (CJK and other input methods) must
// not submit the question; only a real Enter does.
test("Enter during IME composition doesn't submit", async ({ page, api }) => {
  await page.goto("/");
  await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
  await box(page).fill("签名是怎么验证的");
  await box(page).evaluate((el) => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", isComposing: true, bubbles: true, cancelable: true }));
  });
  await expect(box(page)).toHaveValue("签名是怎么验证的"); // not submitted, not cleared
  await box(page).press("Enter");
  await expect.poll(() => api.count("POST /ask")).toBe(1);
});

test("controls: the theme toggle by keyboard and pointer, and the choice survives a reload", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-theme", "light");

  const toggle = page.getByRole("button", { name: "Switch to dark theme" });
  await tabTo(page, toggle);
  await expectVisibleFocus(toggle);
  await page.keyboard.press("Enter");
  await expect(root).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(root).toHaveAttribute("data-theme", "dark");

  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await expect(root).toHaveAttribute("data-theme", "light");
});

test("controls: the repo picker by keyboard, and Ask by pointer", async ({ page, api }) => {
  await page.goto("/");
  await serverUp(api);
  const picker = page.getByRole("combobox", { name: "Repository" });
  await tabTo(page, picker);
  await expectVisibleFocus(picker);
  await page.keyboard.press("ArrowDown");
  await expect(picker).toHaveValue("psf/requests");
  // requests' stored set is its own chunk (slice 5): once it loads, its flagship replaces
  // itsdangerous's, with its label and the list.
  await expect(page.getByRole("region", { name: "Suggested questions" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).not.toHaveText(EXAMPLE.question);
  await expect(page.getByText(/commit 3c7baaa\./)).toBeVisible();

  await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeDisabled(); // empty box
  await box(page).fill(Q);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect.poll(() => api.count("POST /ask")).toBe(1);
});

// Both directions, so a broken motion-safe: variant can't pass by never animating at all.
for (const motion of ["no-preference", "reduce"] as const) {
  test(`the loading pulse ${motion === "reduce" ? "stops" : "runs"} with reduced motion ${motion}`, async ({ page, api }) => {
    await page.emulateMedia({ reducedMotion: motion });
    api.on("POST /ask", held().handler);
    await page.goto("/");
    await serverUp(api);
    await box(page).fill(Q);
    await box(page).press("Enter");
    const pulse = page.getByRole("status").locator("span[aria-hidden='true']");
    await expect(pulse).toBeAttached();
    const animation = await pulse.evaluate((el) => getComputedStyle(el).animationName);
    if (motion === "reduce") expect(animation).toBe("none");
    else expect(animation).not.toBe("none");
  });
}

test("landmarks: one banner, one main, the cited-code aside, a site nav, one h1, a skip target", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("banner")).toHaveCount(1);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("complementary", { name: "Cited code" })).toHaveCount(1);
  await expect(page.getByRole("navigation", { name: "Site" })).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  const target = await page.getByRole("link", { name: "Skip to the question box" }).getAttribute("href");
  await expect(page.locator(target ?? "#missing")).toHaveCount(1);
});

// The stored choice differs from the system setting, so a flash would show as a change of
// data-theme. The observer starts before any page script runs.
for (const [system, stored] of [["light", "dark"], ["dark", "light"]] as const) {
  test(`no theme flash: system ${system}, saved ${stored} -> ${stored} from the first value on`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: system });
    await page.addInitScript((theme) => {
      try { localStorage.setItem("theme", theme); } catch { /* storage blocked */ }
      const seen: string[] = [];
      (window as unknown as { themes: string[] }).themes = seen;
      new MutationObserver(() => {
        const value = document.documentElement?.dataset.theme;
        if (value && seen.at(-1) !== value) seen.push(value);
      }).observe(document, { subtree: true, attributes: true, attributeFilter: ["data-theme"] });
    }, stored);
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", stored);
    await page.waitForLoadState("load");
    expect(await page.evaluate(() => (window as unknown as { themes: string[] }).themes)).toEqual([stored]);
  });
}

// What the phone's keyboard may do to identifiers (docs/smoke-checklist.md S19, Q80): no
// attribute is set today, so the browser's defaults apply. If S19 fails, autoCorrect and
// autoCapitalize go "off" in Composer.tsx and these expected values change with them.
test("the question box's autocapitalize, autocorrect and spellcheck are as shipped", async ({ page }) => {
  await page.goto("/");
  const attributes = await box(page).evaluate((el) =>
    ["autocapitalize", "autocorrect", "spellcheck"].map((name) => el.getAttribute(name)));
  expect(attributes).toEqual([null, null, null]);
});

test("desktop 1440x900: the ask box and Ask are fully visible without scrolling", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/^Example answer/)).toBeVisible();
  await expect(box(page)).toBeInViewport({ ratio: 1 });
  await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeInViewport({ ratio: 1 });
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
});

test.describe("phone 390x844", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("the ask box and Ask are fully visible without scrolling", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/^Example answer/)).toBeVisible();
    await expect(box(page)).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeInViewport({ ratio: 1 });
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
  });
});
