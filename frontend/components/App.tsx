"use client";

import {
  useCallback, useEffect, useReducer, useRef, useState, useSyncExternalStore, type ReactNode,
} from "react";

import { getRepos, getStatus, pollQueue, postAsk } from "../lib/api";
import { DEFAULT_REPO, EXAMPLES, FEATURED } from "../lib/featured";
import { safeGithubUrl } from "../lib/markdown";
import {
  BUSY_MESSAGE, BUSY_OVER_MESSAGE, SETTLING_MESSAGE, WAITING_MESSAGE, canRetry, connectionNote,
  errorMessage, isAlarm, isQueued, loadingMessage, provenance, queuedAnnouncement, queuedMessage,
} from "../lib/messages";
import { IDLE, askReducer, canSubmit, connectionReducer, type Ask } from "../lib/state";
import type { AskResponse, Repo } from "../lib/types";
import { Answer } from "./Answer";
import { Composer } from "./Composer";
import { CodeSheet, EvidencePanel } from "./EvidencePanel";
import { Header } from "./Header";

const API = process.env.NEXT_PUBLIC_API_URL ?? "";
const POLL_MS = 2_500;
const QUEUE_FIRST_POLL_MS = 1_000; // state 5 (Q40): first look ~1 s after asking
const QUEUE_POLL_MS = 3_000; // then every 3 s while the question waits
const DESKTOP = "(min-width: 64rem)"; // Tailwind's lg: side by side from here

// Whether the side panel is on screen; the server can't know, so it renders the phone case.
function subscribeToWidth(onChange: () => void) {
  const query = window.matchMedia(DESKTOP);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
const sidePanelShown = () => window.matchMedia(DESKTOP).matches;

function RetryButton({ onClick, disabled = false, children }: {
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
            className="mt-3 cursor-pointer rounded-control border border-control-edge px-3 py-1.5 text-meta
                       tabular-nums enabled:hover:bg-panel disabled:cursor-not-allowed disabled:opacity-60">
      {children}
    </button>
  );
}

function Ungrounded({ repo, response }: { repo: string; response: AskResponse }) {
  return (
    <div className="text-ui">
      <h2 className="font-serif text-lead font-medium">No cited answer for this question</h2>
      <p className="mt-2">
        The answer couldn&apos;t be tied to lines in {repo}, so it isn&apos;t shown. These files
        came closest:
      </p>
      <ul className="mt-2">
        {response.possibly_relevant.map((file) => {
          const url = safeGithubUrl(file.url);
          const label = `${file.path}:${file.start}-${file.end}`;
          return (
            <li key={file.path} className="py-0.5">
              {url ? (
                <a href={url} target="_blank" rel="noopener noreferrer"
                   className="inline-flex items-center gap-1 text-citation underline">
                  {label}
                  <svg viewBox="0 0 12 12" aria-hidden="true" className="size-3">
                    <path d="M4.5 2.5h-2v7h7v-2M6.5 2.5h3v3M9.5 2.5 5.5 6.5" fill="none"
                          stroke="currentColor" strokeWidth="1.2" />
                  </svg>
                </a>
              ) : label}
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-text-muted">Naming a function or file usually helps.</p>
    </div>
  );
}

/** The message sits in a live region that is always present; the action stays outside it, so
 *  the busy countdown isn't read out every second. */
function AskStatus({ ask, now, online, onRetry, onShowExample }: {
  ask: Ask;
  now: number;
  online: boolean;
  onRetry: () => void;
  onShowExample: () => void;
}) {
  let message: ReactNode = null;
  let action: ReactNode = null;
  let visible: ReactNode = null; // text shown outside the live region (state 5)
  let alarm: ReactNode = null; // a real failure: red, in the assertive region
  const pulse = (
    <span aria-hidden="true" className="size-2 rounded-full bg-citation motion-safe:animate-pulse" />
  );
  switch (ask.kind) {
    case "waiting":
      message = <span className="text-text-muted">{WAITING_MESSAGE}</span>;
      break;
    case "loading":
      if (isQueued(ask.queue)) {
        // The seconds update every poll in a line that is NOT announced; the live region gets
        // only the place, so a screen reader hears it once per position change (Q40).
        visible = (
          <p aria-live="off" className="flex items-center gap-2 text-ui text-text-muted tabular-nums">
            {pulse}{queuedMessage(ask.queue)}
          </p>
        );
        message = <span className="sr-only">{queuedAnnouncement(ask.queue)}</span>;
      } else {
        message = (
          <span className="flex items-center gap-2 text-text-muted">
            {pulse}{loadingMessage(Math.max(0, now - ask.startedAt))}
          </span>
        );
      }
      break;
    case "answered":
      message = <span className="sr-only">Answer ready.</span>;
      break;
    case "ungrounded":
      message = <span className="sr-only">No cited answer for this question.</span>;
      break;
    case "busy": {
      const seconds = Math.max(0, Math.ceil((ask.retryAt - now) / 1000));
      message = seconds > 0 ? BUSY_MESSAGE : BUSY_OVER_MESSAGE;
      action = (
        <RetryButton disabled={seconds > 0} onClick={onRetry}>
          {seconds > 0 ? `Try again in ${seconds} s` : "Try again"}
        </RetryButton>
      );
      break;
    }
    case "error": {
      // Red and assertive only when something on our side failed (round 1, F5); limits,
      // offline and a removed repo are calm, so they stay in the polite status region.
      const text = errorMessage(ask.failure, ask.repo, online);
      if (isAlarm(ask.failure, online)) alarm = <span className="text-error">{text}</span>;
      else message = <span>{text}</span>;
      if (canRetry(ask.failure)) {
        action = <RetryButton onClick={onRetry}>Try again</RetryButton>;
      } else if (EXAMPLES[ask.repo]) {
        action = <RetryButton onClick={onShowExample}>Show the example answer</RetryButton>;
      }
      break;
    }
  }
  return (
    <>
      {visible}
      <div role="status" className="text-ui">{message}</div>
      <div role="alert" className="text-ui">{alarm}</div>
      {action}
    </>
  );
}

function hasQuestion(ask: Ask): ask is Exclude<Ask, { kind: "idle" }> {
  return ask.kind !== "idle";
}

function loadRepos(apply: (repos: Repo[]) => void) {
  void getRepos(fetch, API).then((result) => {
    if (result.ok && result.data.length > 0) apply(result.data);
  });
}

export function App() {
  const [repo, setRepo] = useState(DEFAULT_REPO);
  const [repos, setRepos] = useState(FEATURED);
  const [connection, dispatchConnection] = useReducer(connectionReducer, { kind: "unknown" });
  const [ask, dispatchAsk] = useReducer(askReducer, IDLE);
  const [chosenN, setChosenN] = useState<number | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [now, setNow] = useState(0);
  const lastRequest = useRef(0);
  const sentWaiting = useRef<Ask | null>(null);
  const unmount = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    unmount.current = controller;
    return () => controller.abort();
  }, []);

  // Poll /status on load and while waking (Q14): a visitor is here, so this is not a keep-alive.
  useEffect(() => {
    if (connection.kind !== "unknown" && connection.kind !== "waking") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const result = await getStatus(fetch, API);
      if (cancelled) return;
      // Any JSON from the API, even an error, means the server is awake.
      if (result.ok || result.failure.kind === "api") {
        dispatchConnection({ type: "status_ok" });
        return;
      }
      const at = Date.now();
      setNow(at);
      dispatchConnection({ type: "status_failed", at, online: navigator.onLine });
      timer = setTimeout(poll, POLL_MS);
    }
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [connection.kind]);

  useEffect(() => {
    if (connection.kind === "up") loadRepos(setRepos);
  }, [connection.kind]);

  useEffect(() => {
    if (connection.kind !== "offline") return;
    const retry = () => dispatchConnection({ type: "retry", at: Date.now() });
    window.addEventListener("online", retry);
    return () => window.removeEventListener("online", retry);
  }, [connection.kind]);

  // The waking phases, the loading escalation and the busy countdown all read the clock.
  const ticking = connection.kind === "waking" || ask.kind === "loading" || ask.kind === "busy";
  useEffect(() => {
    if (!ticking) return;
    const interval = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(interval);
  }, [ticking]);

  const send = useCallback(async (requestId: number, target: string, question: string) => {
    const result = await postAsk(fetch, API, target, question, unmount.current?.signal);
    if (result.ok) {
      dispatchAsk({ type: "response", requestId, response: result.data });
      return;
    }
    const at = Date.now();
    setNow(at);
    dispatchAsk({ type: "failure", requestId, failure: result.failure, at });
    if (result.failure.kind === "unreachable") {
      dispatchConnection({ type: "status_failed", at, online: navigator.onLine });
    } else if (result.failure.code === "not_found") {
      loadRepos(setRepos);
    }
  }, []);

  // State 5 (Q40): while a question is loading, ask /status for its place in line. Only while
  // this visitor's question is pending (never idle: not a keep-alive, Q14); chained timeouts so
  // replies can't overlap; stops at position 1 or when the question settles, aborting any poll
  // in flight. A failed poll is ignored: the /ask reply decides the outcome.
  const loadingId = ask.kind === "loading" ? ask.requestId : null;
  const atFront = ask.kind === "loading" && ask.queue?.position === 1;
  useEffect(() => {
    if (loadingId === null || atFront) return;
    const requestId = loadingId;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const result = await pollQueue(fetch, API, controller.signal);
      if (controller.signal.aborted) return;
      if (result.ok) {
        dispatchAsk({ type: "queue_update", requestId, queue: result.queue, at: Date.now() });
      }
      timer = setTimeout(poll, QUEUE_POLL_MS);
    }
    timer = setTimeout(poll, QUEUE_FIRST_POLL_MS);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [loadingId, atFront]);

  // A question asked while the server woke goes out once, when the server is up.
  useEffect(() => {
    if (ask.kind !== "waiting" || connection.kind !== "up" || sentWaiting.current === ask) return;
    sentWaiting.current = ask;
    const requestId = ++lastRequest.current;
    dispatchAsk({ type: "send", requestId, at: Date.now() });
    void send(requestId, ask.repo, ask.question);
  }, [ask, connection.kind, send]);

  function submit(question: string, target = repo) {
    if (!canSubmit(ask)) return;
    const requestId = ++lastRequest.current;
    const at = Date.now();
    const serverUp = connection.kind === "up";
    setNow(at);
    setChosenN(null);
    setSheetOpen(false);
    dispatchAsk({ type: "submit", repo: target, question, requestId, at, serverUp });
    if (serverUp) void send(requestId, target, question);
  }

  function changeRepo(slug: string) {
    setRepo(slug);
    setChosenN(null);
    setSheetOpen(false);
    dispatchAsk({ type: "switch_repo" });
  }

  const openCitation = useCallback((n: number) => {
    setChosenN(n);
    if (!window.matchMedia(DESKTOP).matches) setSheetOpen(true);
  }, []);

  const example = ask.kind === "idle" ? EXAMPLES[repo] : undefined;
  const question = hasQuestion(ask) ? ask.question : example?.question;
  const response = ask.kind === "answered" ? ask.response : example?.response ?? null;
  const openN = chosenN ?? response?.citations.find((c) => c.valid)?.n ?? null;
  const online = typeof navigator === "undefined" || navigator.onLine;
  const panelShown = useSyncExternalStore(subscribeToWidth, sidePanelShown, () => false);
  const panel = <EvidencePanel response={response} openN={openN} onOpen={openCitation} />;

  // One owner per message (round 1, F4): connectionNote() decides, from the state, whether the
  // composer's connection line speaks. Only "down" is red; waking and offline are calm (F5).
  const connectionLine = connectionNote(connection, ask, now);
  const composerStatus = connectionLine ? (
    <p className={connection.kind === "down" ? "text-error" : "text-text-muted"}>
      {connectionLine}{" "}
      {connection.kind === "down" && (
        <button type="button" className="cursor-pointer underline"
                onClick={() => dispatchConnection({ type: "retry", at: Date.now() })}>
          Try again
        </button>
      )}
    </p>
  ) : ask.kind === "idle" && ask.settling !== null ? (
    <p className="text-text-muted">{SETTLING_MESSAGE}</p>
  ) : null;

  function retry() {
    if (ask.kind === "busy" || ask.kind === "error") submit(ask.question, ask.repo);
  }

  return (
    <div className="flex min-h-dvh flex-col lg:h-dvh">
      <a href="#question-box"
         className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-10
                    focus:bg-page focus:p-2">
        Skip to the question box
      </a>
      <Header />
      {/* minmax(0, fr): a column may shrink below its content, so a long code line scrolls
          inside the panel instead of widening it (round 1, F1: at 1024 the panel crushed the
          answer; at 1440 a 300-character line made the page scroll sideways). */}
      <main className="grid flex-1 lg:min-h-0 lg:grid-cols-[minmax(0,53fr)_minmax(0,47fr)]">
        <section aria-labelledby="question"
                 className="reading-scroll flex min-w-0 flex-col px-5 lg:min-h-0 lg:overflow-y-auto lg:px-14">
          <div className="max-w-measure pt-2 pb-8">
            {example && <p className="mb-3 text-meta text-text-muted">{provenance(example)}</p>}
            <h1 id="question" className="font-serif text-title-sm font-medium text-balance lg:text-title">
              {question ?? `Ask a question about the code in ${repo}.`}
            </h1>
            {!question && (
              <p className="mt-4 font-serif text-body">Answers cite the lines they use.</p>
            )}
            <div className="mt-5">
              {response?.answer && (
                <>
                  <Answer markdown={response.answer} citations={response.citations} openN={openN}
                          onOpen={openCitation} sheetOpen={sheetOpen} panelShown={panelShown} />
                  <p className="text-meta text-text-muted lg:hidden">Tap a citation to see the code.</p>
                </>
              )}
              {ask.kind === "ungrounded" && <Ungrounded repo={ask.repo} response={ask.response} />}
              <AskStatus ask={ask} now={now} online={online} onRetry={retry}
                         onShowExample={() => dispatchAsk({ type: "switch_repo" })} />
            </div>
          </div>
          <Composer repo={repo} repos={repos} onRepoChange={changeRepo} onAsk={submit}
                    canAsk={canSubmit(ask)}
                    asking={ask.kind === "loading" || ask.kind === "waiting"}
                    status={composerStatus} />
        </section>
        <aside aria-label="Cited code"
               className="hidden min-h-0 min-w-0 flex-col border-l border-rule bg-panel lg:flex">
          {panel}
        </aside>
      </main>
      <CodeSheet open={sheetOpen} onClose={() => setSheetOpen(false)}>{panel}</CodeSheet>
    </div>
  );
}
