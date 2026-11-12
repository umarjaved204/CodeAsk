// First-load JS of the home page, gzipped (PLAN.md slice 5, step 8: the first-load size rule).
// Run after `npm run build`: node scripts/first-load.mjs [distDir, default .next]
//
// Counts every JS chunk the prerendered "/" references, in a <script> tag or in its inline RSC
// payload (client components hydrate from those). Chunks loaded later with import(), such as
// another repo's suggested answers, are not referenced and are not counted. Gzip at level 9,
// one file at a time, as a static host would serve them.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const dist = process.argv[2] ?? ".next";
const html = readFileSync(join(dist, "server", "app", "index.html"), "utf8");
const chunks = [...new Set([...html.matchAll(/static\/chunks\/[\w.-]+\.js/g)].map((m) => m[0]))];

let total = 0;
for (const chunk of chunks.sort()) {
  const size = gzipSync(readFileSync(join(dist, chunk)), { level: 9 }).length;
  total += size;
  console.log(`${(size / 1024).toFixed(1).padStart(7)} kB  ${chunk}`);
}
console.log(`${(total / 1024).toFixed(1).padStart(7)} kB  total gzip, ${chunks.length} chunks`);
