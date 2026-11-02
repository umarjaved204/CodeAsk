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
  ["ink", "paper", 4.5, "body text"],
  ["ink", "sheet", 4.5, "code text in the panel"],
  ["muted", "paper", 4.5, "provenance, notes"],
  ["muted", "sheet", 4.5, "line numbers, panel meta"],
  ["footnote", "paper", 4.5, "citation figures, links"],
  ["footnote", "sheet", 4.5, "links in the panel"],
  ["mark-ink", "mark", 4.5, "text on the highlighter"],
  ["caution", "paper", 4.5, "unverified citation"],
  ["caution", "sheet", 4.5, "unverified citation in the panel list"],
  ["alert", "paper", 4.5, "error text"],
  ["paper", "ink", 4.5, "button label on the ink button"],
  ["edge", "paper", 3, "input and select borders"],
  ["edge", "sheet", 3, "controls in the panel"],
  ["footnote", "paper", 3, "focus ring"],
  ["mark", "sheet", null, "highlighted lines vs the panel (also marked by text and weight)"],
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
