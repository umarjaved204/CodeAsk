// The featured repos ship as static data, so the first screen works with the backend down
// (PLAN.md slice 3); GET /repos only refines the list. Their suggested questions and stored
// answers are in lib/stored.ts (slice 5).
// featured.json pins each repo's commit (Q52); backend/tests/test_featured.py keeps it equal to
// the backend's config.FEATURED_SHAS.
import featured from "../data/featured.json";
import type { Repo } from "./types";

export const FEATURED: Repo[] = featured.map(({ slug, url }) => ({ slug, url }));

export const DEFAULT_REPO = "pallets/itsdangerous";

/** The featured repo a `?repo=` value names, matched case-insensitively, or null (Q77). The
 *  static list is the only authority: a repo that only GET /repos lists is never opened. */
export function repoFromSearch(search: string): string | null {
  const wanted = new URLSearchParams(search).get("repo")?.toLowerCase();
  return FEATURED.find((r) => r.slug.toLowerCase() === wanted)?.slug ?? null;
}

/** The address of a repo on screen: plain `/` for the default, else `/?repo=owner/name`. */
export function repoAddress(slug: string): string {
  return slug === DEFAULT_REPO ? "/" : `/?repo=${slug}`;
}
