// The deploy settings (PLAN.md Q77): a test per mode of SITE_INDEXABLE and CSP_MODE, the URL
// rules, the exact policy, and the build-log line. The built server's headers are checked once,
// in the enforce mode, by tests/e2e/site.spec.ts.
import { expect, test } from "@playwright/test";

import { cspPolicy, readSiteConfig, securityHeaders, siteConfigSummary } from "../../lib/site-config";

const URLS = { NEXT_PUBLIC_SITE_URL: "https://codeask.example", NEXT_PUBLIC_API_URL: "https://api.example" };
type Flags = Record<string, string | undefined>;
const prod = (extra: Flags = {}) => readSiteConfig({ ...URLS, ...extra }, true);
const header = (extra: Flags, key: string) =>
  securityHeaders(prod(extra), false).find((h) => h.key === key)?.value;

const POLICY = "default-src 'self'; script-src 'self' 'unsafe-inline'; " +
  "style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; " +
  "connect-src 'self' https://api.example; object-src 'none'; base-uri 'none'; " +
  "form-action 'self'; frame-ancestors 'none'";

test("unset flags give the safe defaults: noindex and a report-only policy", () => {
  for (const flags of [{}, { SITE_INDEXABLE: "", CSP_MODE: "" }]) {
    expect(header(flags, "X-Robots-Tag")).toBe("noindex");
    expect(header(flags, "Content-Security-Policy-Report-Only")).toBe(POLICY);
    expect(header(flags, "Content-Security-Policy")).toBeUndefined();
  }
});

test("SITE_INDEXABLE: true drops noindex, false keeps it", () => {
  expect(header({ SITE_INDEXABLE: "true" }, "X-Robots-Tag")).toBeUndefined();
  expect(header({ SITE_INDEXABLE: "false" }, "X-Robots-Tag")).toBe("noindex");
});

test("CSP_MODE: enforce sends the enforced header only, report-only the report-only one", () => {
  expect(header({ CSP_MODE: "enforce" }, "Content-Security-Policy")).toBe(POLICY);
  expect(header({ CSP_MODE: "enforce" }, "Content-Security-Policy-Report-Only")).toBeUndefined();
  expect(header({ CSP_MODE: "report-only" }, "Content-Security-Policy-Report-Only")).toBe(POLICY);
  expect(header({ CSP_MODE: "report-only" }, "Content-Security-Policy")).toBeUndefined();
});

test("a misspelled flag fails the build, naming the variable", () => {
  for (const value of ["yes", "TRUE", "1", "true "]) {
    expect(() => prod({ SITE_INDEXABLE: value })).toThrow(/^SITE_INDEXABLE=/);
  }
  for (const value of ["enforced", "Enforce", "report_only", "off"]) {
    expect(() => prod({ CSP_MODE: value })).toThrow(/^CSP_MODE=/);
  }
});

test("frame and sniffing headers are sent in every mode", () => {
  for (const flags of [{}, { CSP_MODE: "enforce", SITE_INDEXABLE: "true" }]) {
    expect(header(flags, "X-Frame-Options")).toBe("DENY");
    expect(header(flags, "X-Content-Type-Options")).toBe("nosniff");
  }
});

test("a production build requires both URLs", () => {
  expect(() => readSiteConfig({ NEXT_PUBLIC_API_URL: URLS.NEXT_PUBLIC_API_URL }, true))
    .toThrow(/^NEXT_PUBLIC_SITE_URL is required/);
  expect(() => readSiteConfig({ NEXT_PUBLIC_SITE_URL: URLS.NEXT_PUBLIC_SITE_URL }, true))
    .toThrow(/^NEXT_PUBLIC_API_URL is required/);
  expect(() => readSiteConfig({ ...URLS, NEXT_PUBLIC_API_URL: "" }, true))
    .toThrow(/^NEXT_PUBLIC_API_URL is required/);
});

test("the URLs must be bare https origins (http only for local and test hosts)", () => {
  for (const bad of ["https://api.example/", "https://api.example/v1", "https://api.example?x=1",
                     "http://api.example", "https://user:pw@api.example", "api.example", "not a url"]) {
    expect(() => prod({ NEXT_PUBLIC_API_URL: bad }), bad).toThrow(/^NEXT_PUBLIC_API_URL=/);
  }
  for (const good of ["https://api.example", "https://codeask-api.onrender.com",
                      "http://localhost:8000", "http://127.0.0.1:8000", "http://api.test"]) {
    expect(prod({ NEXT_PUBLIC_API_URL: good }).apiOrigin).toBe(good);
  }
});

test("connect-src names the API origin only", () => {
  expect(cspPolicy(prod(), false)).toContain("connect-src 'self' https://api.example;");
});

test("next dev: localhost site URL, no API origin, and 'unsafe-eval' for React's dev tools", () => {
  const dev = readSiteConfig({}, false);
  expect(dev).toEqual({ siteUrl: "http://localhost:3000", apiOrigin: null, indexable: false,
                        cspMode: "report-only" });
  const policy = cspPolicy(dev, true);
  expect(policy).toContain("script-src 'self' 'unsafe-inline' 'unsafe-eval';");
  expect(policy).toContain("connect-src 'self';");
  expect(cspPolicy(prod(), false)).not.toContain("unsafe-eval");
});

test("the build-log line names each value and where the flags came from", () => {
  expect(siteConfigSummary(URLS, prod())).toBe(
    "site config: NEXT_PUBLIC_SITE_URL=https://codeask.example " +
    "NEXT_PUBLIC_API_URL=https://api.example SITE_INDEXABLE=false (default) " +
    "CSP_MODE=report-only (default)");
  const env = { ...URLS, SITE_INDEXABLE: "true", CSP_MODE: "enforce" };
  expect(siteConfigSummary(env, readSiteConfig(env, true))).toContain(
    "SITE_INDEXABLE=true (env) CSP_MODE=enforce (env)");
});
