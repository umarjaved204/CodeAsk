// ESLint (flat config): Next.js's Core Web Vitals and TypeScript rules, plus React's no-danger
// as an error. Model text must never be rendered as HTML (PLAN.md Q17, slice 3 build step 6);
// the one allowed exception is the static theme script in app/layout.tsx, and
// scripts/check.ps1 enforces the same rule independently.
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  { rules: { "react/no-danger": "error" } },
  globalIgnores([".next/**", ".next-e2e/**", "out/**", "next-env.d.ts", "design-review/**"]),
]);
