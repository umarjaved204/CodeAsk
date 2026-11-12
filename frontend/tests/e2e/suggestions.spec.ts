// The suggested questions (PLAN.md slice 5, Q54, step 8). Only itsdangerous q1 is stored before
// generation (step 11), so the cases that need two stored answers or a second exported repo
// (rapid picks between answers, A -> B -> C switches, a failed chunk) are added once they exist.
import fs from "node:fs";
import path from "node:path";

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

// ---------- step 9 (Q55) ----------
test("pre-generated answers with the backend down: the list and a pick work, with no API call", async ({ page, api }) => {
  api.on("GET /status", () => "abort");
  await page.goto("/");
  await expect(page.getByText(/^Waking up the server\./)).toBeVisible();
  await expect(item(page)).toHaveAttribute("aria-current", "true");
  await item(page).click();
  await expect(heading(page)).toHaveText(EXAMPLE.question);
  await expect(heading(page)).toBeFocused();
  await expect(page.getByRole("button", { name: /^Citation 1:/ })).toBeVisible();
  expect(api.count("POST /ask")).toBe(0);
  expect(api.count("GET /repos")).toBe(0);
});

test("switching back to a repo opens its flagship, not the live answer left there", async ({ page, api }) => {
  await up(page, api);
  await ask(page);
  await expect(heading(page)).toHaveText(Q);
  const picker = page.getByRole("combobox", { name: "Repository" });
  await picker.selectOption("psf/requests");
  await expect(heading(page)).toHaveText(/psf\/requests/);
  await picker.selectOption("pallets/itsdangerous");
  await expect(heading(page)).toHaveText(EXAMPLE.question);
  await expect(item(page)).toHaveAttribute("aria-current", "true");
});

test("keyboard: Tab to a suggestion, Enter shows it, focus lands visibly on the question, Tab goes on into the answer", async ({ page, api }) => {
  await up(page, api);
  await ask(page);
  await expect(heading(page)).toHaveText(Q);
  for (let i = 0; i < 60 && !(await item(page).evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(item(page)).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(heading(page)).toHaveText(EXAMPLE.question);
  await expect(heading(page)).toBeFocused();
  expect(await heading(page).evaluate((el) => getComputedStyle(el).outlineStyle)).toBe("solid");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: /^Citation 1:/ })).toBeFocused();
});

// What the page asks the browser for: the scroll itself is the browser's (and instant under
// reduced motion), so the call is recorded rather than timed.
// The target is the block holding the stored answer's label and its question (round s5, F1),
// so both must end up in view.
for (const [width, height] of [[390, 844], [1440, 900]] as const) {
  for (const motion of ["reduce", "no-preference"] as const) {
    test(`at ${width}: a pick brings the label and the question into view, ${motion === "reduce" ? "instantly" : "smoothly"} (reduced motion ${motion})`, async ({ page, api }) => {
      await page.emulateMedia({ reducedMotion: motion });
      await page.addInitScript(() => {
        const calls: unknown[] = [];
        (window as unknown as { scrollCalls: unknown[] }).scrollCalls = calls;
        const original = Element.prototype.scrollIntoView;
        Element.prototype.scrollIntoView = function (this: Element, arg?: boolean | ScrollIntoViewOptions) {
          if (this.querySelector("#question")) calls.push(arg); // the label-and-question block
          return original.call(this, arg);
        };
      });
      await page.setViewportSize({ width, height });
      const long = { ...EXAMPLE.response,
                     answer: Array.from({ length: 10 }, () => EXAMPLE.response.answer).join("\n\n") };
      api.on("POST /ask", () => ({ json: long }));
      await up(page, api);
      await ask(page);
      await expect(heading(page)).toHaveText(Q);
      await item(page).scrollIntoViewIfNeeded();
      await expect(heading(page)).not.toBeInViewport();
      await item(page).click();
      await expect(page.getByText(LABEL)).toBeInViewport({ ratio: 1 });
      await expect(heading(page)).toBeInViewport({ ratio: 1 });
      await expect(heading(page)).toBeFocused();
      const calls = await page.evaluate(() => (window as unknown as { scrollCalls: unknown[] }).scrollCalls);
      expect(calls).toEqual([{ block: "start", behavior: motion === "reduce" ? "instant" : "smooth" }]);
    });
  }
}

// Round s5, F2: the room for the current item's bar must not cost any frozen question (all three
// repos, reserves too) a line at 390, compared with a plain item flush with the "Suggested
// questions" heading at the column's width. The first version (a 14 px inset) failed on two
// express questions; the bar now hangs in the margin (option a).
test("at 390: the room for the bar never adds a line to a frozen question", async ({ page, api }) => {
  const dir = path.resolve(__dirname, "..", "..", "..", "eval", "m2d_questions");
  const questions = fs.readdirSync(dir).filter((f) => f.endsWith(".json")).flatMap((f) => {
    const data = JSON.parse(fs.readFileSync(path.join(dir, f), "utf8"));
    // Failed entries (Q50) count too: the set stays the 24 frozen questions, wherever each sits.
    return [...data.questions, ...data.reserves, ...(data.failed ?? [])]
      .map((q: { question: string }) => q.question);
  });
  expect(questions.length).toBe(24);
  await page.setViewportSize({ width: 390, height: 844 });
  await up(page, api);
  const extra = await item(page).evaluate((current, texts) => {
    const out: string[] = [];
    for (const text of texts) {
      const probe = current.cloneNode() as HTMLElement;
      probe.removeAttribute("aria-current"); // a plain item: no bar, normal weight
      probe.textContent = text;
      current.parentElement!.appendChild(probe);
      const inset = probe.getBoundingClientRect().height; // as shipped
      probe.style.marginLeft = "0px"; // the reference: flush with the heading, column-wide
      probe.style.width = "100%";
      probe.style.paddingLeft = "0px";
      const flush = probe.getBoundingClientRect().height;
      probe.remove();
      if (inset > flush) out.push(text);
    }
    return out;
  }, questions);
  expect(extra).toEqual([]);
});

// Round s5, F2 conditions: the bar and the focus ring hang in the left margin, so no ancestor
// may clip them, and the page must not scroll sideways, at the narrowest widths.
for (const [width, height] of [[390, 844], [320, 568]] as const) {
  test(`at ${width}: the hanging bar and the focus ring are never clipped, and the page never scrolls sideways`, async ({ page, api }) => {
    await page.setViewportSize({ width, height });
    await up(page, api);
    for (let i = 0; i < 60 && !(await item(page).evaluate((el) => el === document.activeElement)); i++) {
      await page.keyboard.press("Tab");
    }
    await expect(item(page)).toBeFocused();
    await expect(item(page)).toHaveAttribute("aria-current", "true");
    const fit = await item(page).evaluate((el) => {
      const s = getComputedStyle(el);
      const ring = parseFloat(s.outlineWidth) + parseFloat(s.outlineOffset);
      const left = el.getBoundingClientRect().left - ring; // the ring's outer edge
      const clippers: string[] = [];
      for (let a = el.parentElement; a; a = a.parentElement) {
        const o = getComputedStyle(a);
        if ((o.overflowX !== "visible" || o.overflowY !== "visible")
            && a.getBoundingClientRect().left > left) clippers.push(a.tagName);
      }
      const root = document.scrollingElement!;
      return { ring, left, barWidth: s.borderLeftWidth, outline: s.outlineStyle, clippers,
               sideways: root.scrollWidth > root.clientWidth };
    });
    expect(fit.outline).toBe("solid"); // the keyboard focus ring is drawn
    expect(fit.barWidth).toBe("2px");
    expect(fit.left).toBeGreaterThanOrEqual(0); // inside the viewport
    expect(fit.clippers).toEqual([]);
    expect(fit.sideways).toBe(false);
  });
}
