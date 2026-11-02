// Slice 3 step 2: render each direction mock to PNGs (desktop + mobile, light + dark) into the
// gitignored design-review/ folder. Run from frontend/: node design/render-directions.mjs
// The mocks load their fonts from Google Fonts, so this needs network access (design time
// only; the app self-hosts fonts via next/font).
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(here, "..", "design-review", "directions");
mkdirSync(out, { recursive: true });
const mock = pathToFileURL(path.join(here, "directions", "index.html")).href;
const sizes = [["desktop", 1440, 900], ["mobile", 390, 844]];

const browser = await chromium.launch();
for (const d of ["a", "b", "c"]) {
  for (const scheme of ["light", "dark"]) {
    for (const [name, width, height] of sizes) {
      const page = await browser.newPage({ viewport: { width, height }, colorScheme: scheme });
      await page.goto(`${mock}?d=${d}`, { waitUntil: "networkidle" });
      await page.evaluate(() => document.fonts.ready);
      const file = path.join(out, `${d}-${name}-${scheme}.png`);
      await page.screenshot({ path: file });
      console.log("wrote", path.relative(process.cwd(), file));
      await page.close();
    }
  }
}
await browser.close();
