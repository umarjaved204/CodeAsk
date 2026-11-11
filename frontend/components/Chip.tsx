"use client";

import type { Citation } from "../lib/types";

const BASE =
  "relative ml-0.5 rounded-cite px-0.5 align-[.45em] font-ui text-micro font-semibold " +
  "not-italic leading-none cursor-pointer " +
  // The highlight must cover the glyphs' whole text box (measured 3px short without this; Q38).
  // The negative margin cancels the padding in layout, so the line around the chip doesn't move.
  "py-[0.25em] -my-[0.25em] " +
  // A 24 px touch target (WCAG 2.5.8) without making the figure look any bigger.
  "after:absolute after:-inset-x-1.5 after:-inset-y-2 after:content-['']";

const HIGHLIGHT = "bg-evidence text-on-evidence forced-colors:outline forced-colors:outline-1";
// Open, but only shown in the side panel: highlighted from lg up, plain below. CSS, so the
// desktop first screen has it from the first paint.
const HIGHLIGHT_WITH_PANEL = "text-citation lg:bg-evidence lg:text-on-evidence " +
  "lg:forced-colors:outline lg:forced-colors:outline-1";

/** A citation that points at supplied lines: opens them in the evidence panel. The
 *  highlighter means "this footnote is open", so on a phone a chip is highlighted only while
 *  its sheet is open (round 1, C2). */
function VerifiedChip({ citation, open, onOpen, sheetOpen, panelShown }: {
  citation: Citation;
  open: boolean;
  onOpen: (n: number) => void;
  sheetOpen: boolean;
  panelShown: boolean;
}) {
  const where = `${citation.path}, lines ${citation.start} to ${citation.end}`;
  // Hover (step 5, W2): a quiet panel tint, only while the chip isn't the open one.
  const style = !open ? "text-citation hover:bg-panel" : sheetOpen ? HIGHLIGHT : HIGHLIGHT_WITH_PANEL;
  return (
    <button
      type="button"
      aria-label={`Citation ${citation.n}: ${where}`}
      aria-current={open && (sheetOpen || panelShown) ? "true" : undefined}
      onClick={() => onOpen(citation.n)}
      className={`${BASE} ${style}`}
    >
      [{citation.n}]
    </button>
  );
}

const noteId = (n: number) => `unverified-note-${n}`;

/** A citation the server couldn't verify: no lines to show, so it explains itself in a note
 *  shown after the block that holds it (round 1, F7), not inside the sentence. */
function UnverifiedChip({ citation, noteOpen, onToggleNote }: {
  citation: Citation;
  noteOpen: boolean;
  onToggleNote: (n: number) => void;
}) {
  return (
    <button
      type="button"
      aria-label={`Citation ${citation.n}, unverified`}
      aria-expanded={noteOpen}
      aria-controls={noteOpen ? noteId(citation.n) : undefined}
      onClick={() => onToggleNote(citation.n)}
      className={`${BASE} text-unverified underline decoration-dashed underline-offset-2 hover:bg-panel`}
    >
      {/* A plain "?" (round 1, F6): the drawn icon read like a no-entry sign at this size. */}
      [{citation.n}?]
    </button>
  );
}

export function UnverifiedNote({ citation }: { citation: Citation }) {
  return (
    <p id={noteId(citation.n)} role="note"
       className="my-2 border-l-2 border-unverified pl-3 font-ui text-meta">
      Unverified: the answer cites {citation.path}, lines {citation.start} to {citation.end},
      which are outside the code the model was given.
    </p>
  );
}

export function Chip({ citation, open, onOpen, sheetOpen, panelShown, noteOpen, onToggleNote }: {
  citation: Citation;
  open: boolean;
  onOpen: (n: number) => void;
  sheetOpen: boolean;
  panelShown: boolean;
  noteOpen: boolean;
  onToggleNote: (n: number) => void;
}) {
  return citation.valid
    ? <VerifiedChip citation={citation} open={open} onOpen={onOpen} sheetOpen={sheetOpen}
                    panelShown={panelShown} />
    : <UnverifiedChip citation={citation} noteOpen={noteOpen} onToggleNote={onToggleNote} />;
}
