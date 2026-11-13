// Renders the link-preview card (design/og-card.html) to app/opengraph-image.png at exactly
// 1200x630 (PLAN.md Q77). Run from frontend/ when the card changes: node design/render-og.mjs
// The PNG is committed; Next serves it and writes the og:image tags. Needs network access for
// Google Fonts (render time only), and fails if a font didn't load rather than ship a fallback.
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const card = pathToFileURL(path.join(here, "og-card.html")).href;
const out = path.join(here, "..", "app", "opengraph-image.png");

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1,
                                       colorScheme: "light" });
  await page.goto(card, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  const missing = await page.evaluate(() =>
    ['600 36px "Newsreader"', '500 60px "Newsreader"', '600 20px "Instrument Sans"', '21px "Fragment Mono"']
      .filter((font) => !document.fonts.check(font)));
  if (missing.length > 0) throw new Error(`fonts not loaded: ${missing.join(", ")}`);
  await page.screenshot({ path: out });
  console.log("wrote", path.relative(process.cwd(), out));
} finally {
  await browser.close();
}
