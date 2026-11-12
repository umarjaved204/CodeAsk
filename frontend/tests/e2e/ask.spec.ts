// The ask flow against the mocked API (PLAN.md slice 3 state inventory, Q18, Q34, Q38).
//
// "First screen with all network blocked" (Done-when) is tested as the API being unreachable,
// not with context.setOffline(true) + reload: there is no service worker, so an offline reload
// would test Chrome's own error page, not ours. Two cases instead: every API request aborted from
// page load (the static example must still render), and the browser going offline after load.
//
// Timers: page.clock.setFixedTime pins Date.now() while the page's real timers keep running, so
// every /status poll and every 1 s tick records an exact fake time, and each threshold is
// checked on both sides.
import type { Locator, Page } from "@playwright/test";

import {
  EMPTY_REPO, EXAMPLE, FIRST_UNVERIFIED, LONG_BLOCK, NOT_OUR_JSON, UNGROUNDED, apiError, expect, held, test,
  type MockApi, type Reply,
} from "./mocks";
import {
  CANT_REACH_MESSAGE, OFFLINE_MESSAGE, dailyLimitMessage, serverErrorMessage,
} from "../../lib/messages";

const Q = "How are signatures verified?";
const LABEL = /^Example answer, generated 2 Nov 2026/;
// Where a refusal can't be retried, the way back is the suggestion list (step 8, D2).
const SUGGESTION = "a suggested question";
const T0 = Date.parse("2026-11-11T10:00:00Z");

async function serverUp(api: MockApi) {
  await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0); // fetched once up
}

// By role: getByLabel("Question") also matches the <section>, named by the h1 ("Ask a question…").
const box = (page: Page) => page.getByRole("textbox", { name: "Question" });

async function ask(page: Page, question = Q) {
  await box(page).fill(question);
  await box(page).press("Enter");
}

/** Wait until two more /status polls have gone out, so the first was fully handled. */
async function twoPolls(api: MockApi) {
  const n = api.count("GET /status");
  await expect.poll(() => api.count("GET /status"), { timeout: 10_000 }).toBeGreaterThanOrEqual(n + 2);
}

const panel = (page: Page) => page.getByRole("complementary", { name: "Cited code" });
const askButton = (page: Page) => page.getByRole("button", { name: /^Ask/ });

/** Line numbers shown in a code region, and which carry the evidence bar. The bar is the
 *  marker that survives forced-colors mode (Q33), so it is the right thing to read here. */
async function shownLines(region: Locator) {
  return region.locator("pre code > span").evaluateAll((spans) => spans.map((s) => ({
    n: Number(s.firstElementChild?.textContent),
    cited: s.className.includes("border-evidence-bar"),
  })));
}

test("ask -> answer -> citation 2 shows only lines 138-142 inside 129-213, with its permalink", async ({ page, api }) => {
  await page.goto("/");
  await serverUp(api);
  await ask(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(Q);

  const chip = page.getByRole("button", { name: "Citation 2: src/itsdangerous/signer.py, lines 138 to 142" });
  await chip.click();
  await expect(chip).toHaveAttribute("aria-current", "true");
  await expect(panel(page)).toContainText("Cited lines 138–142, shown within 129–213");
  const lines = await shownLines(panel(page).getByRole("region", { name: "Code from src/itsdangerous/signer.py" }));
  expect(lines.map((l) => l.n)).toEqual(Array.from({ length: 85 }, (_, i) => 129 + i));
  expect(lines.filter((l) => l.cited).map((l) => l.n)).toEqual([138, 139, 140, 141, 142]);

  const github = panel(page).getByRole("link", { name: "View on GitHub" });
  await expect(github).toHaveAttribute("href",
    `https://github.com/pallets/itsdangerous/blob/${EXAMPLE.commit_sha}/src/itsdangerous/signer.py#L138-L142`);
  await expect(github).toHaveAttribute("target", "_blank");
  await expect(github).toHaveAttribute("rel", "noopener noreferrer");
});

test("the first VALID citation is pre-opened, never an unverified one", async ({ page, api }) => {
  api.on("POST /ask", () => ({ json: FIRST_UNVERIFIED }));
  await page.goto("/");
  await serverUp(api);
  await ask(page);
  await expect(page.getByRole("button", { name: "Citation 1, unverified" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Citation 2:/ })).toHaveAttribute("aria-current", "true");
  await expect(panel(page)).toContainText("Cited lines 138–142, shown within 129–213");
});

test("an unverified chip toggles its inline note and leaves the panel alone", async ({ page, api }) => {
  api.on("POST /ask", () => ({ json: FIRST_UNVERIFIED }));
  await page.goto("/");
  await serverUp(api);
  await ask(page);
  const chip = page.getByRole("button", { name: "Citation 1, unverified" });
  await chip.click();
  await expect(chip).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("note")).toHaveText(
    "Unverified: the answer cites src/itsdangerous/signer.py, lines 67 to 73, which are outside " +
    "the code the model was given.");
  await expect(panel(page)).toContainText("Cited lines 138–142");
  // Round 1, F7: the note follows the paragraph that holds the chip; the sentence stays whole.
  const around = await page.getByRole("note").evaluate((note) => ({
    before: note.previousElementSibling?.textContent ?? "",
    holdsChip: !!note.previousElementSibling?.querySelector('[aria-label="Citation 1, unverified"]'),
  }));
  expect(around.holdsChip).toBe(true);
  expect(around.before).toContain("[1?]. The documentation explicitly states");
  await chip.click();
  await expect(chip).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("note")).toHaveCount(0);
});

test("ungrounded: no answer text, the 3 closest files as safe GitHub links, an empty panel", async ({ page, api }) => {
  api.on("POST /ask", () => ({ json: UNGROUNDED }));
  await page.goto("/");
  await serverUp(api);
  await ask(page);
  await expect(page.getByRole("heading", { name: "No cited answer for this question" })).toBeVisible();
  for (const file of UNGROUNDED.possibly_relevant) {
    const link = page.getByRole("link", { name: `${file.path}:${file.start}-${file.end}` });
    await expect(link).toHaveAttribute("href", file.url);
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  }
  await expect(page.getByText("Naming a function or file usually helps.")).toBeVisible();
  await expect(panel(page)).toHaveText("The cited code appears here.");
});

test("a repo switch mid-request: the old answer never appears, and Ask waits until it settles", async ({ page, api }) => {
  const old = held();
  api.on("POST /ask", old.handler);
  await page.goto("/");
  await serverUp(api);
  await ask(page);
  await expect(page.getByRole("button", { name: "Asking…" })).toBeDisabled();

  await page.getByLabel("Repository").selectOption(EMPTY_REPO);
  await expect(page.getByRole("heading", { level: 1 }))
    .toHaveText(`Ask a question about the code in ${EMPTY_REPO}.`);
  await expect(page.getByText("Finishing the previous question.")).toBeVisible();
  await box(page).fill("A question for requests");
  await expect(askButton(page)).toBeDisabled();

  // Watch the DOM from before the old reply lands until after it settled.
  await page.evaluate(() => {
    new MutationObserver(() => {
      if (document.body.textContent?.includes("STALE ANSWER")) {
        document.documentElement.dataset.sawStale = "yes";
      }
    }).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  old.release({ json: { ...EXAMPLE.response, answer: "STALE ANSWER [1](cite:1)." } });

  await expect(page.getByText("Finishing the previous question.")).toHaveCount(0);
  await expect(askButton(page)).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.dataset.sawStale)).toBeUndefined();
  await expect(page.getByRole("heading", { level: 1 }))
    .toHaveText(`Ask a question about the code in ${EMPTY_REPO}.`);
  expect(api.count("POST /ask")).toBe(1);
});

test("Enter while loading sends nothing", async ({ page, api }) => {
  const reply = held();
  api.on("POST /ask", reply.handler);
  await page.goto("/");
  await serverUp(api);
  await ask(page);
  await expect(page.getByRole("button", { name: "Asking…" })).toBeDisabled();
  await ask(page, "A second question"); // any request it caused would go out right now
  reply.release({ json: EXAMPLE.response });
  await expect(page.getByText("Answer ready.")).toBeAttached();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(Q);
  expect(api.count("POST /ask")).toBe(1);
});

test("a question asked while the server wakes is sent once, when it is up", async ({ page, api }) => {
  let up = false;
  api.on("GET /status", () => up
    ? { json: { ok: true, model: EXAMPLE.model, model_available: true, prompt_version: 3 } }
    : NOT_OUR_JSON);
  await page.goto("/");
  await expect(page.getByText(/^Waking up the server\./)).toBeVisible();
  await ask(page);
  await expect(page.getByText("Your question will be sent when the server is ready.")).toBeVisible();
  expect(api.count("POST /ask")).toBe(0);

  up = true;
  await expect(page.getByText("Answer ready.")).toBeAttached(); // after the next poll (2.5 s)
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(Q);
  expect(api.count("POST /ask")).toBe(1);
});

test("waking: 'Still starting' from 35 s and 'Can't reach' from 90 s, each on both sides", async ({ page, api }) => {
  test.setTimeout(60_000);
  await page.clock.setFixedTime(T0);
  api.on("GET /status", () => NOT_OUR_JSON);
  await page.goto("/");
  const waking = page.getByText(/^Waking up the server\./);
  const starting = page.getByText("Still starting. This is taking longer than usual.");
  const down = page.getByText(CANT_REACH_MESSAGE); // the line also holds "Try again"
  await expect(waking).toBeVisible();

  await page.clock.setFixedTime(T0 + 34_000);
  await twoPolls(api);
  await expect(waking).toBeVisible();
  await page.clock.setFixedTime(T0 + 35_000);
  await expect(starting).toBeVisible();

  await page.clock.setFixedTime(T0 + 89_000);
  await twoPolls(api);
  await expect(starting).toBeVisible();
  await expect(down).toHaveCount(0);
  await page.clock.setFixedTime(T0 + 90_000);
  await expect(down).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
});

test("busy: a countdown from Retry-After, then a manual retry, never an automatic one", async ({ page, api }) => {
  await page.clock.setFixedTime(T0);
  // app.py classify(): Groq's rate limit becomes 503 busy with Retry-After.
  api.on("POST /ask", () => apiError(503, "busy", "The service is busy. Please try again in a minute.",
                                     { "Retry-After": "5" }));
  await page.goto("/");
  await serverUp(api);
  await ask(page);
  await expect(page.getByText(/^The demo is at capacity\./)).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again in 5 s" })).toBeDisabled();

  await page.clock.setFixedTime(T0 + 4_000);
  await expect(page.getByRole("button", { name: "Try again in 1 s" })).toBeDisabled();
  await page.clock.setFixedTime(T0 + 5_000);
  await expect(page.getByText("You can try again now.")).toBeVisible();
  const retry = page.getByRole("button", { name: "Try again", exact: true });
  await expect(retry).toBeEnabled();
  expect(api.count("POST /ask")).toBe(1);

  await retry.click();
  await expect.poll(() => api.count("POST /ask")).toBe(2);
});

// Both directions, so this fails if the page stops reading the header OR if Chromium's hiding of
// unexposed headers (Q38) stops being modelled by the mocks.
for (const [expose, countdown] of [[true, "Try again in 5 s"], [false, "Try again in 60 s"]] as const) {
  test(`busy ${expose ? "with" : "WITHOUT"} Access-Control-Expose-Headers: "${countdown}"`, async ({ page, api }) => {
    await page.clock.setFixedTime(T0);
    // The body of app.py error_json(), as apiError() builds it, with the expose list on or off.
    api.on("POST /ask", () => ({
      status: 503, headers: { "Retry-After": "5" }, expose,
      json: { error: "busy", message: "The service is busy. Please try again in a minute.",
              request_id: "a1b2c3d4" },
    }));
    await page.goto("/");
    await serverUp(api);
    await ask(page);
    await expect(page.getByRole("button", { name: countdown })).toBeDisabled();
  });
}

const FAILURES: { name: string; reply: Reply; text: string; action: string }[] = [
  // app.py refused(): the day's token budget is spent (slice 4; the other refusals: limits.spec).
  { name: "daily limit",
    reply: apiError(429, "daily_limit", "Live questions are used up for now.", { "Retry-After": "7200" }),
    text: dailyLimitMessage(7_200, true),
    action: SUGGESTION },
  // app.py ask(): the model check failed.
  { name: "model unavailable",
    reply: apiError(503, "model_unavailable", "Live answers are unavailable right now."),
    text: "Live answers are unavailable right now. The suggested questions still work.",
    action: SUGGESTION },
  // app.py classify(): anything unexpected.
  { name: "server error", reply: apiError(500, "internal_error", "Something went wrong on the server."),
    text: serverErrorMessage("a1b2c3d4"), action: "Try again" },
  { name: "a reply that isn't our JSON", reply: NOT_OUR_JSON, text: CANT_REACH_MESSAGE,
    action: "Try again" },
  // app.py ask(): HTTPException(404) for a repo that is no longer featured.
  { name: "not found", reply: apiError(404, "not_found", "Unknown repo."),
    text: "pallets/itsdangerous is no longer available here.", action: SUGGESTION },
];

for (const failure of FAILURES) {
  test(`${failure.name}: says so, and offers "${failure.action}"`, async ({ page, api }) => {
    api.on("POST /ask", () => failure.reply);
    await page.goto("/");
    await serverUp(api);
    const reposBefore = api.count("GET /repos");
    await ask(page);
    await expect(page.getByText(failure.text, { exact: true })).toBeVisible();
    if (failure.name === "not found") {
      await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(reposBefore); // list refreshed
    }
    if (failure.action === "Try again") {
      await page.getByRole("button", { name: "Try again", exact: true }).click();
      await expect.poll(() => api.count("POST /ask")).toBe(2);
    } else {
      await expect(page.getByRole("button", { name: "Show the example answer" })).toHaveCount(0);
      await page.getByRole("button", { name: EXAMPLE.question, exact: true }).click();
      await expect(page.getByText(LABEL)).toBeVisible();
      expect(api.count("POST /ask")).toBe(1);
    }
  });
}

test("API unreachable from page load: the static example still renders, with its evidence", async ({ page, api }) => {
  api.on("GET /status", () => "abort");
  await page.goto("/");
  await expect(page.getByText(LABEL)).toBeVisible();
  await expect(page.getByRole("button", { name: /^Citation 1:/ })).toHaveAttribute("aria-current", "true");
  await expect(panel(page)).toContainText("Cited lines 67–73");
  await expect(page.getByText(/^Waking up the server\./)).toBeVisible();
  expect(api.count("GET /repos")).toBe(0);
});

test("offline after load: the example stays; asking says offline and offers a retry", async ({ page, api, context }) => {
  await page.goto("/");
  await serverUp(api);
  api.on("POST /ask", () => "abort"); // in case the request still reaches the route
  await context.setOffline(true);
  await expect(page.getByText(LABEL)).toBeVisible();
  await ask(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(Q);
  await expect(page.getByText(OFFLINE_MESSAGE).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again", exact: true })).toBeVisible();
});

test("no cited line is ever hidden: a 400-line block cited at 350-352 shows and scrolls to them", async ({ page, api }) => {
  api.on("POST /ask", () => ({ json: LONG_BLOCK }));
  await page.goto("/");
  await serverUp(api);
  await ask(page);
  await expect(panel(page)).toContainText("Cited lines 350–352, shown within 1–400");
  const region = panel(page).getByRole("region", { name: "Code from src/long.py" });
  const lines = await shownLines(region);
  expect(lines.map((l) => l.n)).toEqual(Array.from({ length: 400 }, (_, i) => i + 1));
  expect(lines.filter((l) => l.cited).map((l) => l.n)).toEqual([350, 351, 352]);
  for (const i of [349, 350, 351]) {
    await expect(region.locator("pre code > span").nth(i)).toBeInViewport();
  }
});

test("a block the backend didn't send (over its size cap): says so and links to GitHub", async ({ page, api }) => {
  // ask.py evidence(): a block past EVIDENCE_MAX_CHARS is left out and its citation gets block null.
  api.on("POST /ask", () => ({ json: { ...LONG_BLOCK, blocks: [],
    citations: LONG_BLOCK.citations.map((c) => ({ ...c, block: null })) } }));
  await page.goto("/");
  await serverUp(api);
  await ask(page);
  await expect(panel(page)).toContainText("This code is too long to show here. It is on GitHub.");
  await expect(panel(page).getByRole("link", { name: "View on GitHub" }))
    .toHaveAttribute("href", LONG_BLOCK.citations[0].url);
});
