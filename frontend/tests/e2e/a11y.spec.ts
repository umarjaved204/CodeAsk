// Accessibility checks on every built state, in both themes (PLAN.md slice 3 step 6, Q38).
// Axe with the WCAG 2.0/2.1/2.2 A and AA rules: ANY violation fails, with no allowlist.
// "Incomplete" results (things axe can't decide, e.g. contrast over the highlighter) are printed
// for one review by the author, not ignored. Non-text contrast (the 3:1 evidence bar, the
// focus outline) is not an axe rule; design/check-contrast.mjs covers it.
//
// Incomplete review (2026-11-11, mentor-approved; Q38). All were color-contrast, where axe
// couldn't measure the background. Every element sits on a pair check-contrast.mjs verifies:
//   reason                       where                               pair underneath
//   pseudoContent (4-5/state)    composer: repo, counter, box,       text, text-muted, error,
//                                status (the form's ::before fade)   unverified on page
//   elmPartiallyObscured (1)     the open chip: its text box was     FIXED (not a pair question):
//                                taller than its own highlight       the highlight now covers it
//   elmPartiallyObscured (40-44) answer text, panel code lines       text on page (inline code has
//                                (scrolled under the composer or     no background); text on panel;
//                                past the panel's scroll edge)       on-evidence on evidence
//   elmPartiallyObscured (1)     a code line in the mobile sheet     text on panel
//                                (clipped by horizontal scroll)
// The inferred causes were tested below: the fade and the inline code were confirmed; the chip's
// first suspect (its ::after tap area) was WRONG, and axe's own relatedNodes led to the real one.
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import {
  FIRST_UNVERIFIED, NOT_OUR_JSON, UNGROUNDED, apiError, expect, held, statusWith, test,
  type MockApi,
} from "./mocks";
import { DAILY_CAP_MESSAGE, serverErrorMessage } from "../../lib/messages";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const Q = "How are signatures verified?";

const panel = (page: Page) => page.getByRole("complementary", { name: "Cited code" });

async function askAfterUp(page: Page, api: MockApi) {
  await page.goto("/");
  await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
  const box = page.getByRole("textbox", { name: "Question" });
  await box.fill(Q);
  await box.press("Enter");
}

type State = { name: string; setup: (page: Page, api: MockApi) => Promise<void> };

const failing = (reply: ReturnType<typeof apiError>, text: string | RegExp) =>
  async (page: Page, api: MockApi) => {
    api.on("POST /ask", () => reply);
    await askAfterUp(page, api);
    await expect(page.getByText(text)).toBeVisible();
  };

const STATES: State[] = [
  { name: "first screen, evidence open", setup: async (page) => {
    await page.goto("/");
    await expect(panel(page)).toContainText("Cited lines 67–73");
  } },
  { name: "empty (no example yet)", setup: async (page) => {
    await page.goto("/");
    await page.getByRole("combobox", { name: "Repository" }).selectOption("psf/requests");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/psf\/requests/);
  } },
  { name: "loading", setup: async (page, api) => {
    api.on("POST /ask", held().handler);
    await askAfterUp(page, api);
    await expect(page.getByText(/^Answering\./)).toBeVisible();
  } },
  { name: "queued (state 5, provisional shape)", setup: async (page, api) => {
    api.on("GET /status", () => statusWith({ position: 2, wait_s: 40 }));
    api.on("POST /ask", held().handler);
    await askAfterUp(page, api);
    await expect(page.getByText("2nd in line, about 40 seconds.")).toBeVisible();
  } },
  { name: "answered, citation 2 highlighted", setup: async (page, api) => {
    await askAfterUp(page, api);
    await page.getByRole("button", { name: /^Citation 2:/ }).click();
    await expect(panel(page)).toContainText("Cited lines 138–142");
  } },
  { name: "unverified note open", setup: async (page, api) => {
    api.on("POST /ask", () => ({ json: FIRST_UNVERIFIED }));
    await askAfterUp(page, api);
    await page.getByRole("button", { name: "Citation 1, unverified" }).click();
    await expect(page.getByRole("note")).toBeVisible();
  } },
  { name: "ungrounded", setup: async (page, api) => {
    api.on("POST /ask", () => ({ json: UNGROUNDED }));
    await askAfterUp(page, api);
    await expect(page.getByRole("heading", { name: "No cited answer for this question" })).toBeVisible();
  } },
  { name: "waking", setup: async (page, api) => {
    api.on("GET /status", () => NOT_OUR_JSON);
    await page.goto("/");
    await expect(page.getByText(/^Waking up the server\./)).toBeVisible();
  } },
  { name: "busy", setup: failing(apiError(503, "busy", "The service is busy.", { "Retry-After": "30" }),
                                 /^The demo is at capacity\./) },
  { name: "daily cap", setup: failing(apiError(429, "daily_cap", "Daily limit reached."),
                                      DAILY_CAP_MESSAGE) },
  { name: "model unavailable", setup: failing(apiError(503, "model_unavailable", "Unavailable."),
                                              /^Live answers are unavailable right now\./) },
  { name: "server error", setup: failing(apiError(500, "internal_error", "Something went wrong."),
                                         serverErrorMessage("a1b2c3d4")) },
  { name: "not found", setup: failing(apiError(404, "not_found", "Unknown repo."),
                                      "pallets/itsdangerous is no longer available here.") },
  { name: "mobile sheet open, citation 2 highlighted", setup: async (page) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await page.getByRole("button", { name: /^Citation 2:/ }).click();
    await expect(page.getByRole("dialog", { name: "Cited code" })).toContainText("Cited lines 138–142");
  } },
];

for (const state of STATES) {
  for (const theme of ["light", "dark"] as const) {
    test(`axe: ${state.name}, ${theme}`, async ({ page, api }) => {
      await page.emulateMedia({ colorScheme: theme });
      await state.setup(page, api);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
      for (const item of results.incomplete) {
        // Group by axe's own reason (e.g. bgGradient, elmPartiallyObscured), with sample targets.
        const byReason = new Map<string, string[]>();
        for (const node of item.nodes) {
          const reason = String(node.any[0]?.data?.messageKey ?? node.any[0]?.message ?? "unknown");
          byReason.set(reason, [...(byReason.get(reason) ?? []), node.target.join(" ")]);
        }
        const summary = [...byReason].map(([reason, targets]) =>
          `${reason} x${targets.length} (${targets.slice(0, 2).join(" | ")})`).join("; ");
        console.log(`axe incomplete [${state.name}, ${theme}] ${item.id}: ${summary}`);
      }
      expect(results.violations.map((v) =>
        `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
    });
  }
}

type Results = Awaited<ReturnType<AxeBuilder["analyze"]>>;

/** Targets of incomplete color-contrast results with the given axe reason. */
function undecided(results: Results, reason: string): string[] {
  return results.incomplete.filter((i) => i.id === "color-contrast").flatMap((i) => i.nodes)
    .filter((n) => n.any[0]?.data?.messageKey === reason).map((n) => n.target.join(" "));
}

test("confirmed: the composer's fade ::before is what axe couldn't judge (pseudoContent)", async ({ page }) => {
  await page.goto("/");
  await expect(panel(page)).toContainText("Cited lines 67–73");

  // The fade lies entirely ABOVE the form, so it is never behind a control.
  const fade = await page.locator("#ask").evaluate((el) => {
    const s = getComputedStyle(el, "::before");
    return { content: s.content, top: parseFloat(s.top), height: parseFloat(s.height) };
  });
  expect(fade.content).not.toBe("none");
  expect(fade.top + fade.height).toBeLessThanOrEqual(0);

  const before = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(undecided(before, "pseudoContent").length).toBeGreaterThan(0); // control
  await page.addStyleTag({ content: "#ask::before { content: none !important; }" });
  const after = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(undecided(after, "pseudoContent")).toEqual([]);
  expect(after.violations.map((v) => v.id)).toEqual([]);
});

// Axe named the open chip ITSELF as what covered it: with leading-none and no vertical padding,
// its highlight was 12px tall but its text box 15px (measured 2026-11-11: text 364.3-379.3,
// highlight 366.3-378.3), so the glyphs overflowed their own background. Fixed in Chip.tsx with
// vertical padding cancelled by a negative margin. Both themes, since the overflow mattered most
// in dark mode (dark ink on the dark page).
for (const theme of ["light", "dark"] as const) {
  test(`fixed: the open chip's highlight covers its whole text box, and axe can judge it (${theme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme });
    await page.goto("/");
    const chip = page.getByRole("button", { name: /^Citation 1:/ });
    await expect(chip).toHaveAttribute("aria-current", "true");
    const boxes = await chip.evaluate((el) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      const text = range.getBoundingClientRect();
      const own = el.getBoundingClientRect();
      return { textTop: text.top, textBottom: text.bottom, ownTop: own.top, ownBottom: own.bottom };
    });
    expect(boxes.ownTop).toBeLessThanOrEqual(boxes.textTop);
    expect(boxes.ownBottom).toBeGreaterThanOrEqual(boxes.textBottom);

    const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
    expect(undecided(results, "elmPartiallyObscured")
      .filter((t) => t.includes("forced-colors"))).toEqual([]); // the open chip's selector
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`confirmed: inline code in an answer has no background of its own (${theme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme });
    await page.goto("/");
    const code = page.locator(".answer p code").first(); // the example answer has inline code
    await expect(code).toBeVisible();
    expect(await code.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgba(0, 0, 0, 0)");
  });
}

// The highlighter is a background, which forced-colors mode removes; the left bar is a border,
// which survives (Q33). Asserted on computed style, plus a screenshot for a human look.
test("forced colors: cited lines keep a visible 3 px left bar", async ({ page }, testInfo) => {
  await page.emulateMedia({ forcedColors: "active" });
  await page.goto("/");
  await expect(panel(page)).toContainText("Cited lines 67–73");
  const cited = panel(page).locator("pre code > span").first(); // block 67-73 is all cited
  const bar = await cited.evaluate((el) => {
    const s = getComputedStyle(el);
    return { width: s.borderLeftWidth, style: s.borderLeftStyle, color: s.borderLeftColor };
  });
  expect(bar.width).toBe("3px");
  expect(bar.style).toBe("solid");
  expect(bar.color).not.toBe("rgba(0, 0, 0, 0)");
  await panel(page).screenshot({ path: testInfo.outputPath("forced-colors-panel.png") });
});
