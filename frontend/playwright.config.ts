// Playwright (PLAN.md Q18, Q34). The "logic" project runs pure TypeScript tests (reducers, API
// classification) on Playwright's runner without opening a page, so no extra test framework.
// Browser tests against a mocked backend join as a second project.
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  projects: [{ name: "logic", testDir: "./tests/logic" }],
});
