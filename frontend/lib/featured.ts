// The featured repos ship as static data, so the first screen works with the backend down
// (PLAN.md slice 3); GET /repos only refines the list. Each example is a graded fixture
// written by `ask --save` (slice 5 replaces them with the reviewed set).
// featured.json pins each repo's commit (Q52); backend/tests/test_featured.py keeps it equal to
// the backend's config.FEATURED_SHAS.
import featured from "../data/featured.json";
import itsdangerous from "../data/examples/pallets__itsdangerous.json";
import type { Example, Repo } from "./types";

export const FEATURED: Repo[] = featured.map(({ slug, url }) => ({ slug, url }));

export const DEFAULT_REPO = "pallets/itsdangerous";

export const EXAMPLES: Record<string, Example> = {
  "pallets/itsdangerous": itsdangerous as Example,
};
