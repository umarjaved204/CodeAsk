// The privacy text (PLAN.md Q60, Q78): one source in lib/messages.ts. The README block must equal
// its summary (line wrapping aside), and the last-checked date must be a real date.
import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { PRIVACY, PRIVACY_LAST_CHECKED, privacyLastChecked } from "../../lib/messages";

const README = path.join(__dirname, "..", "..", "..", "README.md");
const words = (text: string) => text.split(/\s+/).filter(Boolean).join(" ");

test("the README's privacy block equals PRIVACY.summary", () => {
  const readme = fs.readFileSync(README, "utf8");
  const match = /<!-- privacy:start[^>]*-->([\s\S]*?)<!-- privacy:end -->/.exec(readme);
  expect(match, "privacy markers in README.md").not.toBeNull();
  expect(words(match![1])).toBe(words(PRIVACY.summary));
});

test("PRIVACY_LAST_CHECKED is a real UTC date, shown as day, month and year", () => {
  expect(PRIVACY_LAST_CHECKED).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  const date = new Date(`${PRIVACY_LAST_CHECKED}T00:00:00Z`);
  expect(date.toISOString().slice(0, 10)).toBe(PRIVACY_LAST_CHECKED); // no 2026-02-31 rollover
  expect(date.getTime()).toBeLessThanOrEqual(Date.now());
  expect(privacyLastChecked()).toMatch(/^Last checked \d{1,2} [A-Z][a-z]{2} \d{4}\.$/);
});

test("privacy wording uses curly apostrophes and https links", () => {
  const texts = [PRIVACY.short, PRIVACY.summary, PRIVACY.contact.text,
                 ...PRIVACY.sections.flatMap((s) => [s.heading, ...s.paragraphs])];
  for (const text of texts) expect(text, text).not.toContain("'");
  for (const { href } of [...PRIVACY.links, PRIVACY.contact]) expect(href).toMatch(/^https:\/\//);
});
