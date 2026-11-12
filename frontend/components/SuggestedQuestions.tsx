"use client";

import type { StoredIndex } from "../lib/types";

/** The repo's suggested questions, below the answer (Q54). A pick shows its stored answer at
 *  once; nothing is sent. `current` marks the stored answer on screen, and is null under a
 *  live answer, even one whose text matches a suggestion (step 8 review, item 5). */
export function SuggestedQuestions({ questions, current, onPick }: {
  questions: StoredIndex["questions"];
  current: string | null;
  onPick: (id: string) => void;
}) {
  return (
    <section aria-labelledby="suggested" className="mt-10 border-t border-rule pt-5">
      <h2 id="suggested" className="text-meta font-semibold text-text-muted">Suggested questions</h2>
      <ul className="mt-2">
        {questions.map((q) => (
          <li key={q.id}>
            {/* The current item keeps its place and stays clickable; its mark is a bar and a
                weight change, not colour alone. The text sits flush with the heading at full
                column width (round s5, F2: an inset cost two express questions a line at 390):
                each button starts 14 px into the left margin, which its padding takes back, and
                is 14 px wider. The current item's bar hangs in that margin. Only the current
                item has a border at all: forced-colors mode paints even a transparent border,
                which would bar every item. Its padding is 2 px less, so the text doesn't move. */}
            <button type="button" aria-current={q.id === current ? "true" : undefined}
                    onClick={() => onPick(q.id)}
                    className="-ml-3.5 w-[calc(100%+0.875rem)] cursor-pointer py-1.5 pr-2 pl-3.5 text-left
                               text-ui hover:bg-panel aria-[current=true]:border-l-2
                               aria-[current=true]:border-citation aria-[current=true]:pl-3
                               aria-[current=true]:font-semibold">
              {q.question}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
