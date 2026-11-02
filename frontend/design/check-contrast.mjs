// Checks the colour pairs the design uses against WCAG 2.2 AA, for both themes, reading the
// values straight from app/tokens.css (so it can't drift from them).
// Run from frontend/: node design/check-contrast.mjs   (exit code 1 if any pair fails)
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const css = readFileSync(path.join(here, "..", "app", "tokens.css"), "utf8");

// [foreground, background, minimum ratio, what it is]. 4.5 = text, 3 = UI parts and focus
// (WCAG 1.4.3 / 1.4.11). null = shown for information only.
const PAIRS = [
  // Text: 4.5:1 (WCAG 1.4.3)
  ["text", "page", 4.5, "body text, question"],
  ["text", "panel", 4.5, "code text in the panel"],
  ["text-muted", "page", 4.5, "provenance, notes, placeholder text (inputs sit on page)"],
  ["text-muted", "panel", 4.5, "line numbers, panel meta"],
  ["citation", "page", 4.5, "citation chip text, links"],
  ["citation", "panel", 4.5, "links and citation list in the panel"],
  ["on-evidence", "evidence", 4.5, "open chip text; code and line numbers on the cited range"],
  ["unverified", "page", 4.5, "unverified chip text"],
  ["unverified", "panel", 4.5, "unverified entry in the panel's citation list"],
  ["error", "page", 4.5, "error text"],
  ["on-action", "action", 4.5, "button label"],
  // UI parts: 3:1 (WCAG 1.4.11)
  ["control-edge", "page", 3, "input and select borders"],
  ["control-edge", "panel", 3, "controls in the panel"],
  ["focus", "page", 3, "focus ring on the page"],
  ["focus", "panel", 3, "focus ring in the panel"],
  ["evidence-bar", "panel", 3, "gutter bar vs the panel beside it"],
  ["evidence-bar", "evidence", 3, "gutter bar vs the highlighted line beside it"],
  // For information: the highlight is ALSO marked by the bar, bold numbers and header text.
  ["evidence", "panel", null, "highlighted lines vs the panel"],
];

function themes(source) {
  const out = { light: {}, dark: {} };
  for (const [, selector, body] of source.matchAll(/(:root(?:\[data-theme="dark"\])?)\s*\{([^}]*)\}/g)) {
    const theme = selector.includes("dark") ? "dark" : "light";
    for (const [, name, hex] of body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\b/g)) {
      out[theme][name] = hex;
    }
  }
  return out;
}

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

let failed = 0;
for (const [theme, colours] of Object.entries(themes(css))) {
  console.log(`\n${theme}`);
  for (const [fg, bg, min, what] of PAIRS) {
    if (!colours[fg] || !colours[bg]) throw new Error(`${theme}: missing --${fg} or --${bg}`);
    const r = ratio(colours[fg], colours[bg]);
    const verdict = min === null ? "info" : r >= min ? "ok  " : "FAIL";
    if (verdict === "FAIL") failed += 1;
    console.log(`  ${verdict} ${r.toFixed(2).padStart(5)} (min ${min ?? "-"})  ` +
                `${fg} on ${bg}: ${what}`);
  }
}
console.log(failed ? `\n${failed} pair(s) below WCAG AA` : "\nall pairs meet WCAG AA");
process.exit(failed ? 1 : 0);
