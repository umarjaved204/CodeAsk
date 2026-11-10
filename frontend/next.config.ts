import type { NextConfig } from "next";

// The browser tests build into their own folder (NEXT_DIST_DIR=.next-e2e, set by
// playwright.e2e.config.ts), so they never share `.next` with the dev server or a deploy build.
const config: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
};

export default config;
