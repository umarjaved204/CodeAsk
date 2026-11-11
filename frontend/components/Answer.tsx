"use client";

import {
  createContext, use, useMemo, useState, type ComponentProps, type ReactNode,
} from "react";
import Markdown, { type Components, type ExtraProps } from "react-markdown";

import { ALLOWED_ELEMENTS, citeNumber, citeUrlTransform } from "../lib/markdown";
import type { Citation } from "../lib/types";
import { Chip, UnverifiedNote } from "./Chip";

type Citations = {
  byNumber: Map<number, Citation>;
  openN: number | null;
  onOpen: (n: number) => void;
  sheetOpen: boolean;
  panelShown: boolean;
  noteN: number | null; // the unverified citation whose note is open
  toggleNote: (n: number) => void;
};

// Through context, so `components` below can stay constant: a new function identity would
// remount every chip on each render.
const CitationsContext = createContext<Citations | null>(null);

function CiteLink({ href, children }: ComponentProps<"a">): ReactNode {
  const ctx = use(CitationsContext);
  const n = citeNumber(href);
  const citation = n === null ? undefined : ctx?.byNumber.get(n);
  if (!ctx || !citation) return <>{children}</>; // never a link we didn't make
  return (
    <Chip citation={citation} open={ctx.openN === n} onOpen={ctx.onOpen} sheetOpen={ctx.sheetOpen}
          panelShown={ctx.panelShown} noteOpen={ctx.noteN === n} onToggleNote={ctx.toggleNote} />
  );
}

// ---------- the unverified note, after the block that holds its chip (round 1, F7) ----------
type HastNode = { type: string; tagName?: string; properties?: { href?: unknown }; children?: HastNode[] };
const NESTED_BLOCKS = new Set(["p", "ul", "ol", "li", "blockquote", "pre"]);

/** Citation numbers in a block's own content; nested blocks carry their own notes. */
function citesIn(node: HastNode | undefined): number[] {
  const found: number[] = [];
  for (const child of node?.children ?? []) {
    if (child.type !== "element" || NESTED_BLOCKS.has(child.tagName ?? "")) continue;
    if (child.tagName === "a") {
      const n = citeNumber(typeof child.properties?.href === "string" ? child.properties.href : undefined);
      if (n !== null) found.push(n);
    } else {
      found.push(...citesIn(child));
    }
  }
  return found;
}

function useNoteFor(node: ExtraProps["node"]): Citation | undefined {
  const ctx = use(CitationsContext);
  if (!ctx || ctx.noteN === null) return undefined;
  return citesIn(node as HastNode | undefined).includes(ctx.noteN) ? ctx.byNumber.get(ctx.noteN) : undefined;
}

// Only what the block wrappers use, so one type fits p, li and the headings.
type BlockProps = ExtraProps & { children?: ReactNode };

function Paragraph({ node, children }: BlockProps) {
  const note = useNoteFor(node);
  return <><p>{children}</p>{note && <UnverifiedNote citation={note} />}</>;
}

function ListItem({ node, children }: BlockProps) {
  const note = useNoteFor(node);
  return <li>{children}{note && <UnverifiedNote citation={note} />}</li>;
}

// The question is the page's h1, so headings in an answer start one level down.
function heading(Tag: "h2" | "h3" | "h4") {
  return function Heading({ node, children }: BlockProps) {
    const note = useNoteFor(node);
    return <><Tag>{children}</Tag>{note && <UnverifiedNote citation={note} />}</>;
  };
}

const components: Components = {
  a: CiteLink, p: Paragraph, li: ListItem, h1: heading("h2"), h2: heading("h3"), h3: heading("h4"),
};

/** The space before a citation becomes a no-break space, so a chip never starts a line apart
 *  from the word it cites (round 1, C6). The gap stays visible. */
function keepChipsWithTheirWords(markdown: string): string {
  return markdown.replace(/ (?=\[\d{1,4}\]\(cite:\d{1,4}\))/g, " ");
}

export function Answer({ markdown, citations, openN, onOpen, sheetOpen = false, panelShown = true }: {
  markdown: string;
  citations: Citation[];
  openN: number | null;
  onOpen: (n: number) => void;
  sheetOpen?: boolean; // the mobile sheet is showing the open citation
  panelShown?: boolean; // the side panel is on screen (desktop)
}) {
  // The open unverified note belongs to this answer only.
  const [note, setNote] = useState<{ markdown: string; n: number } | null>(null);
  const noteN = note?.markdown === markdown ? note.n : null;
  const value = useMemo(() => ({
    byNumber: new Map(citations.map((c) => [c.n, c])), openN, onOpen, sheetOpen, panelShown, noteN,
    toggleNote: (n: number) => setNote(noteN === n ? null : { markdown, n }),
  }), [citations, openN, onOpen, sheetOpen, panelShown, noteN, markdown]);
  const text = useMemo(() => keepChipsWithTheirWords(markdown), [markdown]);
  return (
    <CitationsContext value={value}>
      <div className="answer font-serif text-body">
        <Markdown allowedElements={ALLOWED_ELEMENTS} unwrapDisallowed
                  urlTransform={citeUrlTransform} components={components}>
          {text}
        </Markdown>
      </div>
    </CitationsContext>
  );
}
