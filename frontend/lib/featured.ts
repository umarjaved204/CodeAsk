// The featured repos ship as static data, so the first screen works with the backend down
// (PLAN.md slice 3); GET /repos only refines the list. Each example is a graded fixture
// written by `ask --save` (slice 5 replaces them with the reviewed set).
import itsdangerous from "../data/examples/pallets__itsdangerous.json";
import type { Example, Repo } from "./types";

export const FEATURED: Repo[] = [
  { slug: "pallets/itsdangerous", url: "https://github.com/pallets/itsdangerous" },
  { slug: "psf/requests", url: "https://github.com/psf/requests" },
  { slug: "expressjs/express", url: "https://github.com/expressjs/express" },
];

export const DEFAULT_REPO = "pallets/itsdangerous";

export const EXAMPLES: Record<string, Example> = {
  "pallets/itsdangerous": itsdangerous as Example,
};
