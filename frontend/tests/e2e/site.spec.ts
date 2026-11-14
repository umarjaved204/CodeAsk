// Slice 6 step 3b.1-3b.3 (PLAN.md Q77): the deploy headers as the built server sends them, the
// link-preview tags and image, and `?repo=`. The header values per mode are covered by the logic
// tests (tests/logic/site-config.spec.ts); this build is the BUILD_ENV one (CSP enforced,
// SITE_INDEXABLE unset).
import type { Page } from "@playwright/test";

import { API, APP_ORIGIN, BUILD_ENV, EXAMPLE, expect, test, type MockApi } from "./mocks";
import requestsIndex from "../../data/examples/psf__requests/index.json";
import { cspPolicy, readSiteConfig } from "../../lib/site-config";
import { setLoadFailedMessage } from "../../lib/messages";

const REQUESTS = "psf/requests";
const REQUESTS_FLAGSHIP = requestsIndex.questions[0].question;
// Text only the requests set's chunk contains (its flagship question, plain ASCII, so the
// minifier leaves it as is): how the first-load failure test finds that one chunk.
const REQUESTS_CHUNK_MARKER = REQUESTS_FLAGSHIP;
const CHUNKS = "**/_next/static/chunks/*.js";

const heading = (page: Page) => page.getByRole("heading", { level: 1 });
const picker = (page: Page) => page.getByRole("combobox", { name: "Repository" });
const address = (page: Page) => {
  const url = new URL(page.url());
  return url.pathname + url.search;
};

async function open(page: Page, api: MockApi, path: string) {
  await page.goto(path);
  await expect.poll(() => api.count("GET /repos")).toBeGreaterThan(0);
}

// ---------- 3b.2 headers ----------
test("the built server sends the enforced CSP, noindex, nosniff and DENY", async ({ request }) => {
  const response = await request.get("/");
  const headers = response.headers();
  expect(headers["content-security-policy"])
    .toBe(cspPolicy(readSiteConfig(BUILD_ENV, true), false));
  expect(headers["content-security-policy-report-only"]).toBeUndefined();
  expect(headers["x-robots-tag"]).toBe("noindex");
  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["x-content-type-options"]).toBe("nosniff");
});

test("/ preconnects to the API origin (anonymous, like its CORS fetches); /privacy doesn't", async ({ page }) => {
  await page.goto("/");
  const hint = page.locator(`link[rel="preconnect"][href="${API}"]`);
  await expect(hint).toHaveCount(1);
  // React writes crossorigin="" for "anonymous"; HTML treats the empty value as anonymous, so
  // check the parsed state (the IDL property), not the attribute's text.
  expect(await hint.evaluate((link: HTMLLinkElement) => link.crossOrigin)).toBe("anonymous");
  await page.goto("/privacy");
  await expect(page.locator(`link[rel="preconnect"][href="${API}"]`)).toHaveCount(0);
});

// ---------- 3b.1 link previews ----------
const meta = (page: Page, property: string) =>
  page.locator(`meta[property="${property}"], meta[name="${property}"]`).getAttribute("content");

test("link previews: og:url is the site URL and og:image a 1200x630 PNG on it", async ({ page, api, request }) => {
  await open(page, api, "/");
  expect(new URL((await meta(page, "og:url"))!).href).toBe(new URL("/", APP_ORIGIN).href);
  expect(await meta(page, "og:title")).toBe("CodeAsk");
  expect(await meta(page, "og:description")).toBeTruthy();
  expect(await meta(page, "twitter:card")).toBe("summary_large_image");
  expect(await meta(page, "og:image:alt")).toBeTruthy();
  expect(await meta(page, "og:image:width")).toBe("1200");
  expect(await meta(page, "og:image:height")).toBe("630");

  const image = (await meta(page, "og:image"))!;
  expect(image.startsWith(`${APP_ORIGIN}/`)).toBe(true);
  const response = await request.get(image);
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toBe("image/png");
  // A PNG's IHDR chunk holds the width and height as big-endian integers at bytes 16 and 20.
  const png = await response.body();
  expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([1200, 630]);
});

// ---------- 3b.3 ?repo= ----------
test("?repo= opens that featured repo and keeps the address", async ({ page, api }) => {
  await open(page, api, `/?repo=${REQUESTS}`);
  await expect(heading(page)).toHaveText(REQUESTS_FLAGSHIP);
  await expect(picker(page)).toHaveValue(REQUESTS);
  expect(address(page)).toBe(`/?repo=${REQUESTS}`);
});

for (const spelling of ["psf%2Frequests", "PSF/Requests"]) {
  test(`?repo=${spelling} opens psf/requests and the address is normalized`, async ({ page, api }) => {
    await open(page, api, `/?repo=${spelling}`);
    await expect(heading(page)).toHaveText(REQUESTS_FLAGSHIP);
    await expect.poll(() => address(page)).toBe(`/?repo=${REQUESTS}`);
  });
}

// octo/empty is listed by the mocked /repos but isn't featured: the static list decides.
for (const slug of ["evil/unknown", "octo/empty", ""]) {
  test(`?repo=${slug || "(empty)"} opens the default repo at /`, async ({ page, api }) => {
    await open(page, api, `/?repo=${slug}`);
    await expect(heading(page)).toHaveText(EXAMPLE.question);
    await expect(picker(page)).toHaveValue("pallets/itsdangerous");
    await expect.poll(() => address(page)).toBe("/");
  });
}

test("a switch replaces the address without adding history; the default is /", async ({ page, api }) => {
  await open(page, api, "/");
  const entries = await page.evaluate(() => history.length);
  await picker(page).selectOption(REQUESTS);
  await expect(heading(page)).toHaveText(REQUESTS_FLAGSHIP);
  await expect.poll(() => address(page)).toBe(`/?repo=${REQUESTS}`);
  await picker(page).selectOption("pallets/itsdangerous");
  await expect(heading(page)).toHaveText(EXAMPLE.question);
  await expect.poll(() => address(page)).toBe("/");
  expect(await page.evaluate(() => history.length)).toBe(entries);
});

test("a failed first-load chunk keeps the default on screen at /; Try again opens the repo", async ({ page, api }) => {
  // Every chunk loads except the one holding the requests set.
  await page.route(CHUNKS, async (route) => {
    const response = await route.fetch();
    if ((await response.text()).includes(REQUESTS_CHUNK_MARKER)) {
      return route.abort("connectionrefused");
    }
    return route.fulfill({ response });
  });
  await open(page, api, `/?repo=${REQUESTS}`);
  await expect(page.getByText(setLoadFailedMessage(REQUESTS))).toBeVisible();
  await expect(heading(page)).toHaveText(EXAMPLE.question);
  await expect(picker(page)).toHaveValue("pallets/itsdangerous");
  await expect.poll(() => address(page)).toBe("/");
  await page.unroute(CHUNKS);
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(heading(page)).toHaveText(REQUESTS_FLAGSHIP);
  await expect.poll(() => address(page)).toBe(`/?repo=${REQUESTS}`);
  expect(api.count("POST /ask")).toBe(0);
});
