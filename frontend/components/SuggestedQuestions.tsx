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
                weight change, not colour alone. */}
            <button type="button" aria-current={q.id === current ? "true" : undefined}
                    onClick={() => onPick(q.id)}
                    className="w-full cursor-pointer border-l-2 border-transparent py-1.5 pr-2 pl-3
                               text-left text-ui hover:bg-panel aria-[current=true]:border-citation
                               aria-[current=true]:font-semibold">
              {q.question}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
