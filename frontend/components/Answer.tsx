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

// ---------- chips stay with their words (round 1 C6; round 2 R2-1) ----------
// Chromium may break a line on either side of a chip (a <button> is an atomic inline), even
// after a no-break space and before punctuation: round 2 showed chips starting lines and a lone
// "." after a chip. The only reliable fix is a no-wrap group around the word before the chip,
// the chip, and the punctuation right after it. Adjacent chips join one group, and so does an
// inline element (e.g. `code`) directly before a chip. Markdown can't create a <span> and raw
// HTML is never parsed, so the model can't produce one of these.
type HText = { type: "text"; value: string };
type HElement = { type: "element"; tagName: string; properties: Record<string, unknown>; children: HNode[] };
type HNode = HText | HElement | { type: "comment" | "raw" | "doctype"; value?: string };

const isChip = (n: HNode | undefined): n is HElement =>
  n?.type === "element" && n.tagName === "a" &&
  citeNumber(typeof n.properties.href === "string" ? n.properties.href : undefined) !== null;
const TRAILING_PUNCTUATION = /^[.,;:!?)\]}"'’”…]+/;

function groupChips(parent: HElement | { children: HNode[] }) {
  const groups = new Set<HElement>();
  const out: HNode[] = [];
  for (const child of parent.children) {
    if (child.type === "element" && !isChip(child)) groupChips(child);
    if (isChip(child)) {
      const lead: HNode[] = [];
      let last = out.at(-1);
      if (last?.type === "text") {
        const match = /(\S*)(\s*)$/.exec(last.value);
        const tail = match ? match[0] : "";
        if (tail) {
          last.value = last.value.slice(0, last.value.length - tail.length);
          if (!last.value) out.pop();
          lead.unshift({ type: "text", value: tail });
        }
        // Only whitespace was taken: what precedes it (an earlier group, or `code`) joins too.
        if (match && !match[1]) last = out.at(-1);
        else last = undefined;
      }
      if (last && last.type === "element" && (groups.has(last) || last.tagName === "code")) {
        out.pop();
        lead.unshift(...(groups.has(last) ? last.children : [last]));
      }
      const group: HElement = {
        type: "element", tagName: "span", properties: { className: ["whitespace-nowrap"] },
        children: [...lead, child],
      };
      groups.add(group);
      out.push(group);
      continue;
    }
    const previous = out.at(-1);
    if (child.type === "text" && previous?.type === "element" && groups.has(previous)) {
      const punctuation = TRAILING_PUNCTUATION.exec(child.value)?.[0] ?? "";
      if (punctuation) {
        previous.children.push({ type: "text", value: punctuation });
        const rest = child.value.slice(punctuation.length);
        if (rest) out.push({ type: "text", value: rest });
        continue;
      }
    }
    out.push(child);
  }
  parent.children = out;
}

const keepChipsWithTheirWords = () => (tree: { children: HNode[] }) => groupChips(tree);
const REHYPE = [keepChipsWithTheirWords];

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
  return (
    <CitationsContext value={value}>
      <div className="answer font-serif text-body">
        <Markdown allowedElements={ALLOWED_ELEMENTS} unwrapDisallowed rehypePlugins={REHYPE}
                  urlTransform={citeUrlTransform} components={components}>
          {markdown}
        </Markdown>
      </div>
    </CitationsContext>
  );
}
