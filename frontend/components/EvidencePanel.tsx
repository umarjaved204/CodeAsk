"use client";

import { memo, useEffect, useLayoutEffect, useRef, type MouseEvent, type ReactNode } from "react";

import { safeGithubUrl } from "../lib/markdown";
import type { AskResponse, Block, Citation } from "../lib/types";
import { NewTabLink } from "./Header";

// No line cap here: a cited line must never be hidden (mentor review of step 2, 2026-11-11).
// The size bound is the backend's (ask.py evidence(), EVIDENCE_MAX_CHARS): a block over it is
// not sent, and the panel says so and links to GitHub instead.

function GithubLink({ url, children }: { url: string | null; children: ReactNode }) {
  const safe = safeGithubUrl(url);
  if (!safe) return null;
  return (
    <NewTabLink href={safe} className="text-meta text-citation underline">{children}</NewTabLink>
  );
}

function CodeLines({ block, citation }: { block: Block; citation: Citation }) {
  const scroller = useRef<HTMLDivElement>(null);
  const firstCited = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const box = scroller.current;
    const line = firstCited.current;
    if (!box || !line) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    box.scrollTo({ top: Math.max(0, line.offsetTop - box.clientHeight / 3),
                   behavior: reduced ? "instant" : "smooth" });
  }, [citation.n, block]);

  const lines = block.content.split("\n");
  return (
    <div ref={scroller} tabIndex={0} role="region" aria-label={`Code from ${block.path}`}
         translate="no" // code is evidence: never machine-translated (step 5, W5)
         className="relative min-h-0 flex-1 overflow-auto overscroll-contain font-mono text-code">
      <pre className="w-max min-w-full py-2"><code className="block">
        {lines.map((text, i) => {
          const number = block.start + i;
          const cited = number >= citation.start && number <= citation.end;
          return (
            <span key={number} ref={number === citation.start ? firstCited : undefined}
                  // The bar is a border, which survives forced-colors mode; a background doesn't.
                  className={`flex ${cited
                    ? "border-l-[3px] border-evidence-bar bg-evidence text-on-evidence"
                    : "pl-[3px]"}`}>
              <span className={`sticky left-0 w-[7ch] shrink-0 select-none pr-[2ch] text-right ${
                cited ? "bg-evidence font-semibold" : "bg-panel text-text-muted"}`}>
                {number}
              </span>
              <span className="whitespace-pre pr-6">{text}</span>
            </span>
          );
        })}
      </code></pre>
    </div>
  );
}

function CitationList({ citations, openN, onOpen }: {
  citations: Citation[];
  openN: number | null;
  onOpen: (n: number) => void;
}) {
  return (
    <nav aria-label="Citations in this answer"
         className="max-h-[40%] shrink-0 overflow-y-auto overscroll-contain border-t border-rule px-6 py-3">
      <ol>
        {citations.map((c) => {
          const label = `${c.path.split("/").pop()}, lines ${c.start}–${c.end}`;
          if (!c.valid) {
            return (
              <li key={c.n} className="flex gap-2.5 py-1 text-meta text-unverified">
                <span className="w-6 font-semibold">{c.n}</span>
                <span>{label} (unverified)</span>
              </li>
            );
          }
          const open = c.n === openN;
          return (
            <li key={c.n}>
              <button type="button" onClick={() => onOpen(c.n)} aria-current={open ? "true" : undefined}
                      className={`flex w-full cursor-pointer gap-2.5 py-1 text-left text-meta hover:bg-page ${
                        open ? "font-semibold" : ""}`}>
                <span className={`w-6 rounded-cite text-center font-semibold ${
                  open ? "bg-evidence text-on-evidence" : "text-citation"}`}>{c.n}</span>
                <span>{label}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** The cited code. The same panel renders inline on desktop and in the sheet on mobile. */
// memo (step 5, R1): skips the per-second re-renders of App's clock; its props are stable then.
export const EvidencePanel = memo(function EvidencePanel({ response, openN, onOpen }: {
  response: AskResponse | null;
  openN: number | null;
  onOpen: (n: number) => void;
}) {
  const citation = response?.citations.find((c) => c.n === openN);
  if (!response || !citation) {
    return <p className="m-auto p-6 text-meta text-text-muted">The cited code appears here.</p>;
  }
  const block = citation.block === null ? undefined : response.blocks[citation.block];
  const whole = block && block.start === citation.start && block.end === citation.end;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 px-6 pt-5 pb-3">
        <p className="flex items-baseline gap-2.5 text-ui font-semibold">
          <span className="font-serif text-lead font-medium text-citation">{citation.n}</span>
          <span className="break-all" translate="no">{citation.path}</span>
        </p>
        <p className="mt-0.5 text-meta text-text-muted">
          {block && !whole
            ? `Cited lines ${citation.start}–${citation.end}, shown within ${block.start}–${block.end}`
            : `Cited lines ${citation.start}–${citation.end}`}
        </p>
        <p className="mt-1.5"><GithubLink url={citation.url}>View on GitHub</GithubLink></p>
      </div>
      {block ? <CodeLines block={block} citation={citation} /> : (
        <p className="min-h-0 flex-1 px-6 py-2 text-meta text-text-muted">
          This code is too long to show here. It is on GitHub.
        </p>
      )}
      <CitationList citations={response.citations} openN={openN} onOpen={onOpen} />
    </div>
  );
});

/** The mobile bottom sheet: a native dialog handles the focus trap, Esc and returning focus. */
export function CodeSheet({ open, onClose, children }: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);

  // A layout effect, so the sheet is showing before the panel inside measures its scroll.
  useLayoutEffect(() => {
    const element = dialog.current;
    if (open && element && !element.open) element.showModal();
    if (!open && element?.open) element.close();
  }, [open]);

  // A tap on the dimmed backdrop closes the sheet (author's decision, 2026-11-11). The browser
  // reports it as a click on the <dialog> itself, outside its box. Both conditions matter: Enter
  // on a button inside also fires a click, at (0, 0), but its target is that button.
  function closeOnBackdrop(event: MouseEvent<HTMLDialogElement>) {
    if (event.target !== event.currentTarget) return;
    const box = event.currentTarget.getBoundingClientRect();
    const inside = event.clientX >= box.left && event.clientX <= box.right &&
                   event.clientY >= box.top && event.clientY <= box.bottom;
    if (!inside) onClose();
  }

  return (
    <dialog ref={dialog} onClose={onClose} onClick={closeOnBackdrop} aria-label="Cited code"
            className="fixed inset-x-0 top-auto bottom-0 h-[80dvh] w-full max-w-none flex-col
                       rounded-t-sheet bg-panel text-text shadow-sheet backdrop:bg-black/40 open:flex">
      <div className="flex shrink-0 justify-end px-4 pt-3">
        <button type="button" onClick={onClose}
                className="cursor-pointer rounded-control border border-control-edge px-3 py-1 text-meta
                           hover:bg-page">
          Close
        </button>
      </div>
      {open && children}
    </dialog>
  );
}
