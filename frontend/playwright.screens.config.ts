// The step 4 screenshot matrix (PLAN.md Q39, Q41): `npm run screens`, never part of check.ps1.
// Same production build, port and API base as playwright.e2e.config.ts, so the screens show
// exactly what the tests test. One worker, in file order: stable rendering, and the contact
// sheets are built after every shot.
import { defineConfig, devices } from "@playwright/test";

import { APP_ORIGIN, BUILD_ENV, PORT } from "./tests/e2e/mocks";

export default defineConfig({
  testDir: "./design",
  testMatch: "render-states.spec.ts",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: { ...devices["Desktop Chrome"], baseURL: APP_ORIGIN },
  // Three projects: the shots; the same with visible scrollbars (headless hides them; a launch
  // option, so it needs its own project); then the contact sheets, which depend on both and so
  // always run last. If any shot fails, Playwright skips the sheets: fix the shot first.
  projects: [
    { name: "screens", grepInvert: /__scrollbars|contact sheets/ },
    { name: "scrollbars", grep: /__scrollbars/,
      use: { launchOptions: { ignoreDefaultArgs: ["--hide-scrollbars"] } } },
    { name: "sheets", grep: /contact sheets/, dependencies: ["screens", "scrollbars"] },
  ],
  webServer: {
    command: `npm run build && npm run start -- --port ${PORT}`,
    url: APP_ORIGIN,
    reuseExistingServer: false,
    timeout: 180_000,
    env: { ...BUILD_ENV, NEXT_DIST_DIR: ".next-e2e" },
  },
});
