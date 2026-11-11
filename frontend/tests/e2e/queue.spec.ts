// State 5, queued (PLAN.md Q40; the /status `queue` shape is PROVISIONAL until slice 4).
// Polling is measured inside the page: an init script logs the page's own (fake) clock time of
// every /status fetch at the moment it is called, so counts and spacing are exact and "no more
// polls" needs no real-time waiting. Everything else uses the mocks.
import type { Page } from "@playwright/test";

import {
  EXAMPLE, apiError, expect, held, statusWith, test, type MockApi,
} from "./mocks";
import type { QueueWire } from "../../lib/types";

const Q = "How are signatures verified?";
const T0 = new Date("2026-11-11T10:00:00Z");

type Logged = { statusCalls: number[]; sawText: string[]; live: string[] };
const logged = (page: Page): Promise<Logged> => page.evaluate(() => {
  const w = window as unknown as Partial<Logged>;
  return { statusCalls: w.statusCalls ?? [], sawText: w.sawText ?? [], live: w.live ?? [] };
});

async function logStatusCalls(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as Logged;
    w.statusCalls = [];
    const original = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.endsWith("/status")) w.statusCalls.push(Date.now());
      return original(input, init);
    };
  });
}

/** The /status mock answers with whatever `place` holds at the time of the poll. */
function queueScript(api: MockApi) {
  const state: { place: QueueWire | null } = { place: null };
  api.on("GET /status", () => statusWith(state.place));
  return state;
}

async function serverUp(api: MockApi) {
  await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
}

async function ask(page: Page, question = Q) {
  const box = page.getByRole("textbox", { name: "Question" });
  await box.fill(question);
  await box.press("Enter");
}

/** Start the clock frozen after load, so every timer fires at an exact fake time. */
async function frozenAfterLoad(page: Page, api: MockApi) {
  await page.clock.install({ time: T0 });
  await logStatusCalls(page);
  await page.goto("/");
  await serverUp(api);
  await page.clock.pauseAt(new Date(T0.getTime() + 60_000));
}

test("polling: none while idle; first at +1 s, then every 3 s; stops at the front; none after the answer", async ({ page, api }) => {
  const script = queueScript(api);
  const answer = held();
  api.on("POST /ask", answer.handler);
  await frozenAfterLoad(page, api);
  const callsAtLoad = (await logged(page)).statusCalls.length;

  await page.clock.runFor(30_000); // idle: the Q14 rule, no keep-alive polling
  expect((await logged(page)).statusCalls).toHaveLength(callsAtLoad);

  script.place = { position: 3, wait_s: 50 };
  await ask(page);
  const askedAt = await page.evaluate(() => Date.now());
  const since = async () => (await logged(page)).statusCalls.slice(callsAtLoad).map((t) => t - askedAt);

  await page.clock.runFor(999);
  expect(await since()).toEqual([]);
  await page.clock.runFor(1);
  await expect(page.getByText("3rd in line, about 50 seconds.")).toBeVisible();
  expect(await since()).toEqual([1_000]);

  script.place = { position: 2, wait_s: 20 };
  await page.clock.runFor(3_000);
  await expect(page.getByText("2nd in line, about 20 seconds.")).toBeVisible();
  expect(await since()).toEqual([1_000, 4_000]);

  // Reaching the front: "Answering…" again, and the 12 s escalation counts from here (+7 s).
  script.place = { position: 1, wait_s: 0 };
  await page.clock.runFor(3_000);
  await expect(page.getByText("Answering. This usually takes a few seconds.")).toBeVisible();
  expect(await since()).toEqual([1_000, 4_000, 7_000]);
  await page.clock.runFor(11_000);
  await expect(page.getByText("Answering. This usually takes a few seconds.")).toBeVisible();
  await page.clock.runFor(1_000);
  await expect(page.getByText(/^Still working\./)).toBeVisible();
  expect(await since()).toEqual([1_000, 4_000, 7_000]); // stopped at position 1

  answer.release({ json: EXAMPLE.response });
  await expect(page.getByText("Answer ready.")).toBeAttached();
  await page.clock.runFor(30_000);
  expect(await since()).toEqual([1_000, 4_000, 7_000]); // none after the answer
});

test("polling stops when the question ends in an error", async ({ page, api }) => {
  const script = queueScript(api);
  const answer = held();
  api.on("POST /ask", answer.handler);
  await frozenAfterLoad(page, api);
  script.place = { position: 3, wait_s: 50 };
  await ask(page);
  await page.clock.runFor(1_000);
  await expect(page.getByText("3rd in line, about 50 seconds.")).toBeVisible();
  const calls = (await logged(page)).statusCalls.length;

  answer.release(apiError(500, "internal_error", "Something went wrong on the server."));
  await expect(page.getByText(/^The server couldn't answer/)).toBeVisible();
  await page.clock.runFor(30_000);
  expect((await logged(page)).statusCalls).toHaveLength(calls);
});

test("the live region announces position changes only; the visible line keeps its seconds current", async ({ page, api }) => {
  const script = queueScript(api);
  api.on("POST /ask", held().handler);
  await frozenAfterLoad(page, api);
  script.place = { position: 3, wait_s: 50 };
  await ask(page);
  await page.clock.runFor(1_000);
  const region = page.getByRole("status").filter({ hasText: "3rd in line." });
  await expect(region).toHaveText("3rd in line.");
  await region.evaluate((el) => {
    const w = window as unknown as Logged;
    w.live = [];
    new MutationObserver(() => w.live.push(el.textContent ?? ""))
      .observe(el, { subtree: true, childList: true, characterData: true });
  });
  const live = async () => (await logged(page)).live;

  script.place = { position: 3, wait_s: 40 }; // only the seconds change
  await page.clock.runFor(3_000);
  await expect(page.getByText("3rd in line, about 40 seconds.")).toBeVisible();
  script.place = { position: 3, wait_s: 30 };
  await page.clock.runFor(3_000);
  await expect(page.getByText("3rd in line, about 30 seconds.")).toBeVisible();
  expect(await live()).toEqual([]); // nothing announced

  script.place = { position: 2, wait_s: 20 }; // the position changes
  await page.clock.runFor(3_000);
  await expect(page.getByText("2nd in line, about 20 seconds.")).toBeVisible();
  await expect.poll(live).not.toEqual([]);
  expect(new Set(await live())).toEqual(new Set(["2nd in line."]));

  // The visible line is not a live region.
  await expect(page.getByText("2nd in line, about 20 seconds.")).toHaveAttribute("aria-live", "off");
});

test("a poll that returns after the answer never shows a queue", async ({ page, api }) => {
  const answer = held();
  const poll = held();
  api.on("POST /ask", answer.handler);
  await page.goto("/");
  await serverUp(api);
  const statusBefore = api.count("GET /status");
  api.on("GET /status", poll.handler); // the next poll hangs
  await ask(page);
  await expect.poll(() => api.count("GET /status")).toBeGreaterThan(statusBefore); // ~1 s

  await page.evaluate(() => {
    const w = window as unknown as Logged;
    w.sawText = [];
    new MutationObserver(() => {
      if (document.body.textContent?.includes("in line")) w.sawText.push("in line");
    }).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  answer.release({ json: EXAMPLE.response });
  await expect(page.getByText("Answer ready.")).toBeAttached();
  poll.release(statusWith({ position: 2, wait_s: 40 }));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(Q);
  expect((await logged(page)).sawText).toEqual([]);
});

test("a failed poll while loading changes nothing; the /ask reply decides", async ({ page, api }) => {
  const answer = held();
  api.on("POST /ask", answer.handler);
  await page.goto("/");
  await serverUp(api);
  const before = api.count("GET /status");
  api.on("GET /status", () => ({ status: 502, body: "<html>Bad gateway</html>", contentType: "text/html" }));
  await ask(page);
  await expect.poll(() => api.count("GET /status"), { timeout: 10_000 }).toBeGreaterThanOrEqual(before + 2);
  await expect(page.getByText("Answering. This usually takes a few seconds.")).toBeVisible();
  await expect(page.getByText(/^Waking up the server/)).toHaveCount(0);

  answer.release({ json: EXAMPLE.response });
  await expect(page.getByText("Answer ready.")).toBeAttached();
});

test("a repo switch while queued: the queue line goes, polling stops, Ask waits to settle", async ({ page, api }) => {
  const script = queueScript(api);
  const old = held();
  api.on("POST /ask", old.handler);
  await frozenAfterLoad(page, api);
  script.place = { position: 2, wait_s: 40 };
  await ask(page);
  await page.clock.runFor(1_000);
  await expect(page.getByText("2nd in line, about 40 seconds.")).toBeVisible();

  await page.getByRole("combobox", { name: "Repository" }).selectOption("psf/requests");
  await expect(page.getByRole("heading", { level: 1 }))
    .toHaveText("Ask a question about the code in psf/requests.");
  await expect(page.getByText(/in line/)).toHaveCount(0);
  await expect(page.getByText("Finishing the previous question.")).toBeVisible();
  const calls = (await logged(page)).statusCalls.length;
  await page.clock.runFor(30_000);
  expect((await logged(page)).statusCalls).toHaveLength(calls);

  old.release({ json: EXAMPLE.response });
  await expect(page.getByText("Finishing the previous question.")).toHaveCount(0);
  await page.getByRole("textbox", { name: "Question" }).fill("Next");
  await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeEnabled();
  await expect(page.getByText(/in line/)).toHaveCount(0);
});
