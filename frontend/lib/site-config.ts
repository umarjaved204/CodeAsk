// Deploy settings read from the environment at build time (PLAN.md slice 6, Q77). next.config.ts
// calls readSiteConfig() when the config loads, so a bad value stops the build before anything
// deploys; layout.tsx reads the site URL from it for link previews. Vercel bakes next.config
// headers into the build, so every value here changes only with a redeploy.
//
// - The two flags: unset (or empty) = the safe default (noindex on, CSP report-only); a value
//   that isn't one of the accepted spellings fails the build, so a typo such as
//   CSP_MODE=enforced can't quietly leave the policy unenforced.
// - The two URLs: required in production builds; bare origins only (no path, no trailing
//   slash), https, or http for local and test hosts. `next dev` falls back to localhost.
// Server-side only (next.config.ts and the root layout): nothing here reaches the browser.

export type CspMode = "report-only" | "enforce";

export type SiteConfig = {
  siteUrl: string;
  apiOrigin: string | null; // null only in development, with NEXT_PUBLIC_API_URL unset
  indexable: boolean;
  cspMode: CspMode;
};

type Env = Record<string, string | undefined>;

const DEV_SITE_URL = "http://localhost:3000";
const PLAIN_HTTP_HOSTS = new Set(["localhost", "127.0.0.1", "api.test"]); // api.test: the e2e mock

function set(env: Env, name: string): string | undefined {
  const value = env[name];
  return value === undefined || value === "" ? undefined : value;
}

function flag<T extends string>(env: Env, name: string, accepted: readonly T[], fallback: T): T {
  const value = set(env, name);
  if (value === undefined) return fallback;
  if (!(accepted as readonly string[]).includes(value)) {
    throw new Error(`${name}=${JSON.stringify(value)} is not accepted: use one of ` +
                    `${accepted.join(", ")}, or leave it unset for ${fallback}.`);
  }
  return value as T;
}

function origin(env: Env, name: string, production: boolean): string | null {
  const value = set(env, name);
  if (value === undefined) {
    if (production) throw new Error(`${name} is required in a production build.`);
    return null;
  }
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`${name}=${JSON.stringify(value)} is not a URL.`);
  }
  if (url.origin !== value) {
    throw new Error(`${name}=${JSON.stringify(value)} must be a bare origin such as ` +
                    `https://example.com (no path, query or trailing slash).`);
  }
  if (url.protocol !== "https:" && !(url.protocol === "http:" && PLAIN_HTTP_HOSTS.has(url.hostname))) {
    throw new Error(`${name}=${JSON.stringify(value)} must use https.`);
  }
  return value;
}

export function readSiteConfig(env: Env, production: boolean): SiteConfig {
  return {
    siteUrl: origin(env, "NEXT_PUBLIC_SITE_URL", production) ?? DEV_SITE_URL,
    apiOrigin: origin(env, "NEXT_PUBLIC_API_URL", production),
    indexable: flag(env, "SITE_INDEXABLE", ["true", "false"], "false") === "true",
    cspMode: flag(env, "CSP_MODE", ["report-only", "enforce"], "report-only"),
  };
}

/** One build-log line with the effective values and where each flag came from. */
export function siteConfigSummary(env: Env, config: SiteConfig): string {
  const source = (name: string) => (set(env, name) === undefined ? "default" : "env");
  return `site config: NEXT_PUBLIC_SITE_URL=${config.siteUrl} ` +
         `NEXT_PUBLIC_API_URL=${config.apiOrigin ?? "(unset)"} ` +
         `SITE_INDEXABLE=${config.indexable} (${source("SITE_INDEXABLE")}) ` +
         `CSP_MODE=${config.cspMode} (${source("CSP_MODE")})`;
}

/** CSP option 3 (Q56, Q77): no nonces, so inline scripts are allowed (Next's bootstrap and the
 *  theme script); everything else is locked. connect-src names only the API's origin. img-src
 *  starts at 'self': data: or blob: is added only if the enforced e2e run shows a violation.
 *  No upgrade-insecure-requests: it is ignored in report-only mode, and enforced it would
 *  rewrite the e2e's http://api.test. 'unsafe-eval' only under `next dev` (React's dev tools). */
export function cspPolicy(config: SiteConfig, dev: boolean): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self'",
    "font-src 'self'",
    `connect-src 'self'${config.apiOrigin ? ` ${config.apiOrigin}` : ""}`,
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

/** The headers on every path. X-Frame-Options stands in for frame-ancestors while the policy is
 *  report-only (browsers ignore frame-ancestors there). */
export function securityHeaders(config: SiteConfig, dev: boolean): { key: string; value: string }[] {
  return [
    { key: config.cspMode === "enforce" ? "Content-Security-Policy" : "Content-Security-Policy-Report-Only",
      value: cspPolicy(config, dev) },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    ...(config.indexable ? [] : [{ key: "X-Robots-Tag", value: "noindex" }]),
  ];
}
