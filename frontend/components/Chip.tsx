"use client";

import { useId, useState } from "react";

import type { Citation } from "../lib/types";

const BASE =
  "relative ml-0.5 rounded-cite px-0.5 align-[.45em] font-ui text-micro font-semibold " +
  "not-italic leading-none cursor-pointer " +
  // The highlight must cover the glyphs' whole text box (measured 3px short without this; Q38).
  // The negative margin cancels the padding in layout, so the line around the chip doesn't move.
  "py-[0.25em] -my-[0.25em] " +
  // A 24 px touch target (WCAG 2.5.8) without making the figure look any bigger.
  "after:absolute after:-inset-x-1.5 after:-inset-y-2 after:content-['']";

/** A citation that points at supplied lines: opens them in the evidence panel. */
function VerifiedChip({ citation, open, onOpen }: {
  citation: Citation;
  open: boolean;
  onOpen: (n: number) => void;
}) {
  const where = `${citation.path}, lines ${citation.start} to ${citation.end}`;
  return (
    <button
      type="button"
      aria-label={`Citation ${citation.n}: ${where}`}
      aria-current={open ? "true" : undefined}
      onClick={() => onOpen(citation.n)}
      className={`${BASE} ${open
        ? "bg-evidence text-on-evidence forced-colors:outline forced-colors:outline-1"
        : "text-citation"}`}
    >
      [{citation.n}]
    </button>
  );
}

/** A citation the server couldn't verify: no lines to show, so it explains itself in place. */
function UnverifiedChip({ citation }: { citation: Citation }) {
  const [expanded, setExpanded] = useState(false);
  const noteId = useId();
  return (
    <>
      <button
        type="button"
        aria-label={`Citation ${citation.n}, unverified`}
        aria-expanded={expanded}
        aria-controls={expanded ? noteId : undefined}
        onClick={() => setExpanded((value) => !value)}
        className={`${BASE} text-unverified underline decoration-dashed underline-offset-2`}
      >
        [{citation.n}
        <svg viewBox="0 0 12 12" aria-hidden="true" className="mx-px inline size-2.5 align-[-1px]">
          <circle cx="6" cy="6" r="5" fill="none" stroke="currentColor" strokeWidth="1.2" />
          <path d="M4.6 4.7a1.4 1.4 0 1 1 2.2 1.2c-.5.3-.8.6-.8 1.1M6 8.9v.1" fill="none"
                stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
        ]
      </button>
      {expanded && (
        <span id={noteId} role="note"
              className="my-2 block border-l-2 border-unverified pl-3 font-ui text-meta">
          Unverified: the answer cites {citation.path}, lines {citation.start} to {citation.end},
          which are outside the code the model was given.
        </span>
      )}
    </>
  );
}

export function Chip({ citation, open, onOpen }: {
  citation: Citation;
  open: boolean;
  onOpen: (n: number) => void;
}) {
  return citation.valid
    ? <VerifiedChip citation={citation} open={open} onOpen={onOpen} />
    : <UnverifiedChip citation={citation} />;
}
