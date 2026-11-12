// The featured repos ship as static data, so the first screen works with the backend down
// (PLAN.md slice 3); GET /repos only refines the list. Their suggested questions and stored
// answers are in lib/stored.ts (slice 5).
// featured.json pins each repo's commit (Q52); backend/tests/test_featured.py keeps it equal to
// the backend's config.FEATURED_SHAS.
import featured from "../data/featured.json";
import type { Repo } from "./types";

export const FEATURED: Repo[] = featured.map(({ slug, url }) => ({ slug, url }));

export const DEFAULT_REPO = "pallets/itsdangerous";
