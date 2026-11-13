import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

import { readSiteConfig, securityHeaders, siteConfigSummary } from "./lib/site-config";

// Deploy settings (PLAN.md Q77): validated here, so a missing URL or a misspelled flag stops the
// build; the effective values are printed in the build log.
export default function config(phase: string): NextConfig {
  const dev = phase === PHASE_DEVELOPMENT_SERVER;
  const site = readSiteConfig(process.env, !dev);
  console.log(siteConfigSummary(process.env, site));
  return {
    // The browser tests build into their own folder (NEXT_DIST_DIR=.next-e2e, set by
    // playwright.e2e.config.ts), so they never share `.next` with the dev server or a deploy build.
    distDir: process.env.NEXT_DIST_DIR ?? ".next",
    async headers() {
      return [{ source: "/(.*)", headers: securityHeaders(site, dev) }];
    },
  };
}
