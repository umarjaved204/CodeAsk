// The step 4 screenshot matrix (PLAN.md Q39, Q41): every state at the widths where it can break,
// from the same mocks and production build as the e2e suite. REVIEW MATERIAL, NOT ASSERTIONS:
// a shot fails only if its state can't be reached; layout problems go into notes.md.
//
// Run: npm run screens (ROUND=<n> for later rounds). Output: design-review/round-<n>/ with one
// PNG per shot, contact sheets (sheet__*.png), notes.md and manifest.json.
//
// Determinism: the clock is installed, then frozen with pauseAt after load; timed states are
// reached with runFor, so timers fire at exact fake times and nothing ticks between the state
// and the shot. Reduced motion, animations disabled, caret hidden, fonts loaded.
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { test as plain, type Page } from "@playwright/test";

import {
  FIRST_UNVERIFIED, LONG_BLOCK, NOT_OUR_JSON, UNGROUNDED, apiError, expect, held, statusWith, test,
  type MockApi, type Reply,
} from "../tests/e2e/mocks";
import {
  CANT_REACH_MESSAGE, IN_PROGRESS_MESSAGE, OFFLINE_MESSAGE, dailyLimitMessage, pausedMessage,
  perVisitorMessage, serverErrorMessage,
} from "../lib/messages";
import { LONG_ANSWER, LONG_LINES, MANY_CITATIONS, SPECIMEN } from "./screen-fixtures";

const ROUND = process.env.ROUND ?? "1";
const OUT = path.resolve(__dirname, "..", "design-review", `round-${ROUND}`);
const NOTES = path.join(OUT, "notes");
const T0 = new Date("2026-11-11T10:00:00Z");
const Q = "How are signatures verified?";
const HEIGHT: Record<number, number> = {
  320: 568, 390: 844, 768: 1024, 844: 390, 1023: 768, 1024: 768, 1440: 900, 1920: 1080,
};

type Theme = "light" | "dark";
// "scrollbars": a viewport shot with the browser's scrollbars shown (headless hides them; on
// Windows a classic scrollbar takes ~17 px from the reading column; mentor, round 1, C4).
type Capture = "viewport" | "mid" | "end" | "expanded" | "scrollbars";
type Setup = (page: Page, api: MockApi, width: number) => Promise<void>;

// ---------- reaching each state ----------
async function load(page: Page, api: MockApi, waitForUp = true) {
  await page.goto("/");
  if (waitForUp) await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
  await page.clock.pauseAt(new Date(T0.getTime() + 10_000)); // freeze from here on
}

async function ask(page: Page, question = Q) {
  const box = page.getByRole("textbox", { name: "Question" });
  await box.fill(question);
  await box.press("Enter");
}

const replying = (reply: Reply, ready: string | RegExp): Setup => async (page, api) => {
  api.on("POST /ask", () => reply);
  await load(page, api);
  await ask(page);
  await expect(page.getByText(ready).first()).toBeAttached();
};

const answered = (json: unknown, openInSheet = false, ready: string | RegExp = "Answer ready."):
    Setup => async (page, api, width) => {
  await replying({ json }, ready)(page, api, width);
  if (openInSheet && width < 1024) {
    await page.getByRole("button", { name: /^Citation 1:/ }).click();
    await expect(page.getByRole("dialog", { name: "Cited code" })).toBeVisible();
  }
};

const loading = (runMs: number, ready: string | RegExp): Setup => async (page, api) => {
  api.on("POST /ask", held().handler);
  await load(page, api);
  await ask(page);
  if (runMs) await page.clock.runFor(runMs);
  await expect(page.getByText(ready)).toBeVisible();
};

const waking = (runMs: number, ready: string | RegExp): Setup => async (page, api) => {
  api.on("GET /status", () => NOT_OUR_JSON);
  await load(page, api, false);
  // The first failed /status must have landed (connection "waking", its clock started) before
  // time moves: fast-forwarding while the page is still "unknown" advances nothing.
  await expect(page.getByText(/^Waking up the server\./)).toBeVisible();
  if (runMs) await page.clock.runFor(runMs);
  await expect(page.getByText(ready)).toBeVisible();
};

const STATES: Record<string, Setup> = {
  "01-first-screen": async (page, api) => {
    await load(page, api);
    await expect(page.getByText(/^Example answer/)).toBeVisible();
  },
  "02-empty": async (page, api) => {
    await load(page, api);
    await page.getByRole("combobox", { name: "Repository" }).selectOption("psf/requests");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/psf\/requests/);
  },
  "03-loading": loading(0, /^Answering\./),
  "03b-still-working": loading(12_000, /^Still working\./),
  "04-waking": waking(0, /^Waking up the server\./),
  "04b-still-starting": waking(35_000, /^Still starting\./),
  // 95 s: "down" needs a failed poll >= 90 s after the first failure, which may have landed
  // just after the freeze.
  "04c-cant-reach": waking(95_000, CANT_REACH_MESSAGE),
  "05-queued": async (page, api) => {
    api.on("GET /status", () => statusWith({ position: 2, wait_s: 40 }));
    await loading(1_000, "Next in line, up to about 40 seconds.")(page, api, 0);
  },
  "06-busy": replying(apiError(503, "busy", "The service is busy.", { "Retry-After": "30" }),
                      /^The demo is at capacity\./),
  // Slice 4 (Q45, step 8): the refusals from /ask, and the service line on load.
  "07-daily-limit": replying(apiError(429, "daily_limit", "Used up.", { "Retry-After": "7200" }),
                             dailyLimitMessage(7_200, false)),
  "07b-per-visitor": replying(apiError(429, "per_ip_limit", "Limit.", { "Retry-After": "10800" }),
                              perVisitorMessage(10_800, false)),
  "07c-in-progress": replying(apiError(429, "in_progress", "Still answering.", { "Retry-After": "40" }),
                              IN_PROGRESS_MESSAGE),
  "07d-paused-refused": replying(apiError(503, "paused", "Paused."), pausedMessage(false)),
  "20-paused-on-load": async (page, api) => {
    api.on("GET /status", () => statusWith(null, "paused"));
    await load(page, api);
    await expect(page.getByText(pausedMessage(true))).toBeVisible();
  },
  "21-daily-limit-on-load": async (page, api) => { // the longest line in the sticky composer
    api.on("GET /status", () => statusWith(null, "daily_limit", 7_200));
    await load(page, api);
    await expect(page.getByText(dailyLimitMessage(7_200, true))).toBeVisible();
  },
  "08-model-unavailable": replying(apiError(503, "model_unavailable", "Unavailable."),
                                   /^Live answers are unavailable right now\./),
  "09-server-error": replying(apiError(500, "internal_error", "Something went wrong."),
                              serverErrorMessage("a1b2c3d4")),
  "09b-offline": async (page, api) => {
    api.on("POST /ask", () => "abort");
    await load(page, api);
    await page.context().setOffline(true);
    await ask(page);
    await expect(page.getByText(OFFLINE_MESSAGE).first()).toBeVisible();
  },
  "10-ungrounded": answered(UNGROUNDED, false, "No cited answer for this question."),
  "11-unverified-note": async (page, api, width) => {
    await answered(FIRST_UNVERIFIED)(page, api, width);
    await page.getByRole("button", { name: "Citation 1, unverified" }).click();
    await expect(page.getByRole("note")).toBeVisible();
  },
  "12-long-answer": answered(LONG_ANSWER),
  "13-long-lines": answered(LONG_LINES, true),
  "14-many-citations": answered(MANY_CITATIONS),
  "15-sheet-open": async (page, api) => {
    await load(page, api);
    await page.getByRole("button", { name: /^Citation 2:/ }).click();
    await expect(page.getByRole("dialog", { name: "Cited code" })).toBeVisible();
  },
  "16-input-limit": async (page, api) => {
    await load(page, api);
    const text = "How does key rotation work when the list of secret keys grows over time? ".repeat(6);
    await page.getByRole("textbox", { name: "Question" }).fill(text.slice(0, 385));
    await expect(page.getByText("385 / 400")).toBeVisible();
  },
  "17-block-not-sent": answered({
    ...LONG_BLOCK, blocks: [], citations: LONG_BLOCK.citations.map((c) => ({ ...c, block: null })),
  }, true),
  "18-specimen": answered(SPECIMEN),
  "19-not-found": replying(apiError(404, "not_found", "Unknown repo."),
                           "pallets/itsdangerous is no longer available here."),
};

// ---------- the matrix (Q41) ----------
type Shot = { state: string; width: number; theme: Theme; capture: Capture };
const shots: Shot[] = [];
const add = (state: string, width: number, theme: Theme, capture: Capture = "viewport") =>
  shots.push({ state, width, theme, capture });
const BOTH: Theme[] = ["light", "dark"];

for (const state of ["01-first-screen", "10-ungrounded", "11-unverified-note"]) {
  for (const width of [390, 768, 1024, 1440]) for (const theme of BOTH) add(state, width, theme);
}
for (const width of [390, 768, 1023]) for (const theme of BOTH) add("15-sheet-open", width, theme);
for (const state of Object.keys(STATES)) {
  if (["01-first-screen", "10-ungrounded", "11-unverified-note", "15-sheet-open"].includes(state)) continue;
  add(state, 1440, "light");
  add(state, 390, "light");
  add(state, 1440, "dark");
}
for (const state of ["12-long-answer", "13-long-lines", "14-many-citations"]) {
  add(state, 768, "light");
  add(state, 1024, "light");
}
add("01-first-screen", 320, "light");
add("14-many-citations", 320, "light");
// Step 8 (mentor): the longest service line where the sticky composer is tightest.
add("21-daily-limit-on-load", 320, "light");
add("21-daily-limit-on-load", 390, "dark");
add("01-first-screen", 1920, "light");
// Round 2 additions (mentor, round 1): a short landscape phone, and visible scrollbars.
for (const state of ["01-first-screen", "12-long-answer"]) {
  add(state, 844, "light");
  add(state, 1440, "light", "scrollbars");
}
for (const width of [1440, 390]) {
  add("12-long-answer", width, "light", "mid");
  add("12-long-answer", width, "light", "end");
  add("18-specimen", width, "light", "expanded");
}

const fileName = (s: Shot) =>
  `${s.state}__${s.width}-${s.theme}${s.capture === "viewport" ? "" : `__${s.capture}`}`;

// ---------- captures and notes ----------
async function prepareCapture(page: Page, capture: Capture) {
  if (capture === "mid" || capture === "end") {
    await page.evaluate((where) => {
      const section = document.querySelector<HTMLElement>("section[aria-labelledby='question']");
      const inner = section !== null && section.scrollHeight > section.clientHeight + 1 &&
        getComputedStyle(section).overflowY !== "visible";
      const box = inner ? section : document.scrollingElement;
      if (!box) return;
      const max = box.scrollHeight - box.clientHeight;
      box.scrollTop = where === "end" ? max : Math.round(max / 2);
    }, capture);
  }
  if (capture === "expanded") { // typography only: NOT what a visitor sees
    await page.addStyleTag({ content:
      ".lg\\:h-dvh { height: auto !important; } " +
      "section[aria-labelledby='question'] { overflow: visible !important; }" });
  }
}

/** Automatic notes (Q41): never assertions, only material for the review. */
async function notesFor(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    const label = (el: Element) => {
      const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/).slice(0, 3) : [];
      return `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""}${cls.length ? `.${cls.join(".")}` : ""}`;
    };
    const shown = (el: HTMLElement) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && !el.closest(".sr-only") &&
        getComputedStyle(el).visibility !== "hidden";
    };
    const doc = document.documentElement;
    if (doc.scrollWidth > doc.clientWidth) {
      out.push(`the page scrolls sideways: ${doc.scrollWidth}px of content in ${doc.clientWidth}px`);
    }
    const all = [...document.querySelectorAll<HTMLElement>("body *")].filter(shown);
    for (const el of all) {
      const s = getComputedStyle(el);
      if ((s.overflowX === "hidden" || s.overflowX === "clip") && el.scrollWidth > el.clientWidth + 1) {
        out.push(`clipped sideways: ${label(el)} (${el.scrollWidth}px in ${el.clientWidth}px)`);
      }
    }
    const small: string[] = [];
    for (const el of all) {
      const ownText = [...el.childNodes].some((n) => n.nodeType === Node.TEXT_NODE && n.textContent?.trim());
      const size = parseFloat(getComputedStyle(el).fontSize);
      if (ownText && size < 12) small.push(`${size}px "${el.textContent?.trim().slice(0, 40)}"`);
    }
    if (small.length) out.push(`text under 12px: ${small.slice(0, 5).join("; ")}`);
    const p = document.querySelector<HTMLElement>(".answer p");
    if (p && shown(p)) {
      const s = getComputedStyle(p);
      const ctx = document.createElement("canvas").getContext("2d");
      const sample = p.textContent ?? "";
      if (ctx && sample.length > 20) {
        ctx.font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
        const perChar = ctx.measureText(sample).width / sample.length;
        const ratio = parseFloat(s.lineHeight) / parseFloat(s.fontSize);
        out.push(`reading measure: ~${Math.round(p.clientWidth / perChar)} characters per line ` +
                 `(target 45-75); line-height ${Number.isFinite(ratio) ? ratio.toFixed(2) : s.lineHeight}`);
      }
    }
    const form = document.querySelector("#ask");
    if (form) {
      const top = form.getBoundingClientRect().top;
      const under = [...document.querySelectorAll<HTMLElement>(".answer p, .answer li, .answer pre, h1")]
        .filter((el) => { const r = el.getBoundingClientRect(); return r.bottom > top - 24 && r.top < top; });
      if (under.length) out.push(`text under the composer's fade (${under.length}): ${label(under[0])}`);
    }
    return out.length ? out : ["nothing noted"];
  });
}

async function shoot(shot: Shot, page: Page, api: MockApi) {
  await page.setViewportSize({ width: shot.width, height: HEIGHT[shot.width] });
  await page.emulateMedia({ colorScheme: shot.theme, reducedMotion: "reduce" });
  await page.clock.install({ time: T0 });
  await STATES[shot.state](page, api, shot.width);
  await page.evaluate(async () => { await document.fonts.ready; });
  await prepareCapture(page, shot.capture);

  fs.mkdirSync(NOTES, { recursive: true });
  await page.screenshot({
    path: path.join(OUT, `${fileName(shot)}.png`), animations: "disabled", caret: "hide",
    fullPage: shot.capture === "expanded",
  });
  const notes = await notesFor(page);
  fs.writeFileSync(path.join(NOTES, `${fileName(shot)}.md`),
                   `## ${fileName(shot)}\n${notes.map((n) => `- ${n}`).join("\n")}\n`);
}

// Shots named "__scrollbars" run in the config's "scrollbars" project, whose browser shows
// scrollbars; Playwright allows a different launch only per project, not per describe group.
for (const shot of shots) {
  test(fileName(shot), async ({ page, api }) => shoot(shot, page, api));
}

// ---------- contact sheets, notes.md, manifest.json (runs last; plain test: no offsite guard,
// since the sheets load the PNGs from disk via file://) ----------
plain("contact sheets, notes and manifest", async ({ page }) => {
  const pngs = fs.readdirSync(OUT).filter((f) => f.endsWith(".png") && !f.startsWith("sheet__")).sort();
  const groups = new Map<string, string[]>();
  for (const file of pngs) {
    const pass = file.split("__")[1].replace(".png", ""); // e.g. "1440-light"
    groups.set(pass, [...(groups.get(pass) ?? []), file]);
  }
  const sheets: string[] = [];
  for (const [pass, files] of groups) {
    const width = Number(pass.split("-")[0]);
    const narrow = width <= 400;
    const perSheet = narrow ? 8 : 6;
    const tile = narrow ? width : 720; // phone widths at ~100%, wider shots scaled to 720px
    for (let i = 0; i < files.length; i += perSheet) {
      const chunk = files.slice(i, i + perSheet);
      const name = `sheet__${pass}__${i / perSheet + 1}`;
      const html = `<!doctype html><meta charset="utf-8"><body style="margin:0;padding:16px;` +
        `background:#888;font:600 20px system-ui;display:grid;gap:16px;` +
        `grid-template-columns:repeat(${narrow ? 3 : 2},${tile}px);width:max-content">` +
        chunk.map((f) => `<figure style="margin:0;background:#fff;padding:6px">` +
          `<figcaption style="padding:4px 0 8px">${f.replace(".png", "")}</figcaption>` +
          `<img src="${encodeURI(f)}" style="width:${tile}px;display:block"></figure>`).join("") +
        `</body>`;
      const htmlPath = path.join(OUT, `${name}.html`);
      fs.writeFileSync(htmlPath, html);
      await page.setViewportSize({ width: 1500, height: 900 });
      await page.goto(pathToFileURL(htmlPath).href);
      await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
      sheets.push(`${name}.png`);
    }
  }

  const notes = fs.existsSync(NOTES)
    ? fs.readdirSync(NOTES).sort().map((f) => fs.readFileSync(path.join(NOTES, f), "utf8")).join("\n")
    : "";
  fs.writeFileSync(path.join(OUT, "notes.md"),
                   `# Round ${ROUND}: automatic notes (review material, not assertions)\n\n${notes}`);

  const git = (args: string) => execSync(`git ${args}`, { encoding: "utf8" }).trim();
  const manifest = {
    round: ROUND, commit: git("rev-parse HEAD"), dirty: git("status --porcelain") !== "",
    date: new Date().toISOString(), shots: pngs.length, sheets,
  };
  fs.writeFileSync(path.join(OUT, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
  console.log(`round ${ROUND}: ${pngs.length} shots, ${sheets.length} sheets in ${OUT}`);
});
