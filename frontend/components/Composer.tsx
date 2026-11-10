"use client";

import { useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";

import type { Repo } from "../lib/types";

const MAX_CHARS = 400;
const WARN_CHARS = 380;

/** The sticky ask box: always in view, at the bottom of the reading column. */
export function Composer({ repo, repos, onRepoChange, onAsk, canAsk, asking, status }: {
  repo: string;
  repos: Repo[];
  onRepoChange: (slug: string) => void;
  onAsk: (question: string) => void;
  canAsk: boolean;
  asking: boolean;
  status: ReactNode;
}) {
  const [question, setQuestion] = useState("");
  const ready = canAsk && question.trim().length > 0;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    onAsk(question.trim());
    setQuestion("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      submit(event);
    }
  }

  return (
    <form id="ask" onSubmit={submit}
          className="sticky bottom-0 mt-auto max-w-measure bg-page pt-3 pb-4
                     before:pointer-events-none before:absolute before:inset-x-0 before:-top-6
                     before:h-6 before:bg-linear-to-t before:from-page before:to-transparent">
      <div role="status" className="min-h-0 text-meta">{status}</div>
      <div className="mt-2 flex items-center justify-between gap-3">
        <label className="sr-only" htmlFor="repo">Repository</label>
        <select id="repo" value={repo} onChange={(e) => onRepoChange(e.target.value)}
                className="rounded-control border border-control-edge bg-page px-2.5 py-1.5 text-meta">
          {repos.map((r) => <option key={r.slug} value={r.slug}>{r.slug}</option>)}
        </select>
        <span className={`text-micro ${question.length >= WARN_CHARS ? "text-unverified" : "text-text-muted"}`}>
          {question.length} / {MAX_CHARS}
        </span>
      </div>
      <div className="mt-2 flex items-stretch gap-2.5">
        <label className="sr-only" htmlFor="question-box">Question</label>
        <textarea id="question-box" rows={2} maxLength={MAX_CHARS} value={question}
                  onChange={(e) => setQuestion(e.target.value)} onKeyDown={onKeyDown}
                  placeholder={`Ask about the code in ${repo}`}
                  className="min-w-0 flex-1 resize-none rounded-control border border-control-edge
                             bg-transparent px-3 py-2 text-ui placeholder:text-text-muted" />
        <button type="submit" disabled={!ready}
                className="cursor-pointer rounded-control bg-action px-5 text-ui font-semibold
                           text-on-action disabled:cursor-not-allowed disabled:opacity-60">
          {asking ? "Asking…" : "Ask"}
        </button>
      </div>
      <p className="mt-2 text-micro text-text-muted">
        Answers use only the code of the featured repos and cite the lines they rely on.
        Rate-limited demo; each question is answered on its own.
      </p>
    </form>
  );
}
