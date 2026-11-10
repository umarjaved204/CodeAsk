// Browser tests against a mocked API (PLAN.md slice 3, step 2; Q18). A separate config, not a
// project in playwright.config.ts: `webServer` belongs to the whole config and starts for every
// run, even `--project=logic` (measured 2026-11-11), so the fast logic tests stay build-free.
//
// The server is a production build (`next build && next start`), not the dev server: it tests
// what ships, without hydration noise. It builds into its own folder (.next-e2e) with the API
// base set to http://api.test, a reserved name that never resolves, so a missing mock can't reach
// a real backend. Chromium only; Safari's <dialog> is covered by the real-phone check in slice 6.
import { defineConfig, devices } from "@playwright/test";

import { API, APP_ORIGIN, PORT } from "./tests/e2e/mocks";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  reporter: "list",
  use: { baseURL: APP_ORIGIN },
  projects: [
    { name: "e2e", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
  webServer: {
    command: `npm run build && npm run start -- --port ${PORT}`,
    url: APP_ORIGIN,
    reuseExistingServer: false,
    timeout: 180_000,
    env: { NEXT_PUBLIC_API_URL: API, NEXT_DIST_DIR: ".next-e2e" },
  },
});
