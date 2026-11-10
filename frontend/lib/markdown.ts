// The safety rules for model-written markdown (PLAN.md Q17, Q34). Pure, so the logic tests
// cover them directly. The server already strips model links and images; these rules are the
// second layer, in case anything gets through.

// Everything else is unwrapped to its text. No images, tables or raw HTML.
export const ALLOWED_ELEMENTS = [
  "p", "strong", "em", "code", "pre", "ul", "ol", "li", "blockquote", "h1", "h2", "h3", "h4",
  "a", "br", "hr",
];

const CITE = /^cite:(\d{1,4})$/;

/** The only URLs an answer may contain are server-made citation markers. */
export function citeUrlTransform(url: string): string {
  return CITE.test(url) ? url : "";
}

/** The citation number of a `cite:n` link, or null for anything else. */
export function citeNumber(href: string | undefined): number | null {
  const match = href?.match(CITE);
  return match ? Number(match[1]) : null;
}

/** Permalinks come from the server, but are still checked before becoming a link. */
export function safeGithubUrl(url: string | null | undefined): string | null {
  return url?.startsWith("https://github.com/") ? url : null;
}
