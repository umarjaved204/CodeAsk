// The step 4 screenshot matrix (PLAN.md Q39, Q41): `npm run screens`, never part of check.ps1.
// Same production build, port and API base as playwright.e2e.config.ts, so the screens show
// exactly what the tests test. One worker, in file order: stable rendering, and the contact
// sheets are built after every shot.
import { defineConfig, devices } from "@playwright/test";

import { API, APP_ORIGIN, PORT } from "./tests/e2e/mocks";

export default defineConfig({
  testDir: "./design",
  testMatch: "render-states.spec.ts",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: { ...devices["Desktop Chrome"], baseURL: APP_ORIGIN },
  webServer: {
    command: `npm run build && npm run start -- --port ${PORT}`,
    url: APP_ORIGIN,
    reuseExistingServer: false,
    timeout: 180_000,
    env: { NEXT_PUBLIC_API_URL: API, NEXT_DIST_DIR: ".next-e2e" },
  },
});
