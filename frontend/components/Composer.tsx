"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";

import { PRIVACY } from "../lib/messages";
import type { Repo } from "../lib/types";
import { NewTabLink } from "./Header";

const MAX_CHARS = 400;
const WARN_CHARS = 380;

/** The sticky ask box: always in view, at the bottom of the reading column. On short screens
 *  (under 500 px tall) it isn't sticky and drops its footer note, so the answer comes first. */
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
  const form = useRef<HTMLFormElement>(null);

  // Step 5, W1 (WCAG 2.4.11): publish the composer's height, plus the fade above it, so the
  // page's scroll padding keeps a focused element out from under it. The height changes (the
  // status line, wrapping at narrow widths), and it is 0 where the composer isn't sticky.
  useEffect(() => {
    const element = form.current;
    if (!element) return;
    const root = document.documentElement;
    const publish = () => {
      const sticky = getComputedStyle(element).position === "sticky";
      root.style.setProperty("--composer-height", sticky ? `${element.offsetHeight + 24}px` : "0px");
    };
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(element);
    window.addEventListener("resize", publish);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", publish);
      root.style.removeProperty("--composer-height");
    };
  }, []);

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
    <form id="ask" ref={form} onSubmit={submit}
          className="sticky bottom-0 mt-auto max-w-measure bg-page pt-3 pb-4
                     before:pointer-events-none before:absolute before:inset-x-0 before:-top-6
                     before:h-6 before:bg-linear-to-t before:from-page before:to-transparent
                     short:static short:before:hidden">
      <div role="status" className="min-h-0 text-meta">{status}</div>
      <div className="mt-2 flex items-center justify-between gap-3">
        <label className="sr-only" htmlFor="repo">Repository</label>
        <select id="repo" name="repo" autoComplete="off" translate="no" value={repo}
                onChange={(e) => onRepoChange(e.target.value)}
                className="rounded-control border border-control-edge bg-page px-2.5 py-1.5 text-meta">
          {repos.map((r) => <option key={r.slug} value={r.slug}>{r.slug}</option>)}
        </select>
        <span className={`text-micro tabular-nums ${question.length >= WARN_CHARS ? "text-unverified" : "text-text-muted"}`}>
          {question.length} / {MAX_CHARS}
        </span>
      </div>
      <div className="mt-2 flex items-stretch gap-2.5">
        <label className="sr-only" htmlFor="question-box">Question</label>
        <textarea id="question-box" name="question" autoComplete="off" rows={2} maxLength={MAX_CHARS}
                  value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={onKeyDown}
                  placeholder={`Ask about the code in ${repo}…`}
                  className="min-w-0 flex-1 resize-none rounded-control border border-control-edge
                             bg-transparent px-3 py-2 text-ui placeholder:text-text-muted" />
        <button type="submit" disabled={!ready}
                className="cursor-pointer rounded-control bg-action px-5 text-ui font-semibold
                           text-on-action enabled:hover:bg-action-hover disabled:cursor-not-allowed
                           disabled:opacity-60">
          {asking ? "Asking…" : "Ask"}
        </button>
      </div>
      {/* The privacy sentence replaces "Rate-limited demo; each question is answered on its
          own." (Q78), so the note never gains a line (site.spec.ts measures it). */}
      <p className="mt-2 text-micro text-text-muted short:hidden">
        Answers use only the code of the featured repos and cite the lines they rely on.{" "}
        {PRIVACY.short}{" "}
        <NewTabLink href="/privacy" className="underline">Privacy</NewTabLink>
      </p>
    </form>
  );
}
