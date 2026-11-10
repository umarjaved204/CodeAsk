"use client";

import { createContext, use, useMemo, type ComponentProps, type ReactNode } from "react";
import Markdown, { type Components } from "react-markdown";

import { ALLOWED_ELEMENTS, citeNumber, citeUrlTransform } from "../lib/markdown";
import type { Citation } from "../lib/types";
import { Chip } from "./Chip";

type Citations = {
  byNumber: Map<number, Citation>;
  openN: number | null;
  onOpen: (n: number, opener: HTMLElement) => void;
};

// Through context, so `components` below can stay constant: a new function identity would
// remount every chip on each render and lose an open unverified note.
const CitationsContext = createContext<Citations | null>(null);

function CiteLink({ href, children }: ComponentProps<"a">): ReactNode {
  const citations = use(CitationsContext);
  const n = citeNumber(href);
  const citation = n === null ? undefined : citations?.byNumber.get(n);
  if (!citations || !citation) return <>{children}</>; // never a link we didn't make
  return <Chip citation={citation} open={citations.openN === n} onOpen={citations.onOpen} />;
}

// The question is the page's h1, so headings in an answer start one level down.
const components: Components = {
  a: CiteLink,
  h1: ({ children }) => <h2>{children}</h2>,
  h2: ({ children }) => <h3>{children}</h3>,
  h3: ({ children }) => <h4>{children}</h4>,
};

export function Answer({ markdown, citations, openN, onOpen }: {
  markdown: string;
  citations: Citation[];
  openN: number | null;
  onOpen: (n: number, opener: HTMLElement) => void;
}) {
  const value = useMemo(
    () => ({ byNumber: new Map(citations.map((c) => [c.n, c])), openN, onOpen }),
    [citations, openN, onOpen],
  );
  return (
    <CitationsContext value={value}>
      <div className="answer font-serif text-body">
        <Markdown allowedElements={ALLOWED_ELEMENTS} unwrapDisallowed
                  urlTransform={citeUrlTransform} components={components}>
          {markdown}
        </Markdown>
      </div>
    </CitationsContext>
  );
}
