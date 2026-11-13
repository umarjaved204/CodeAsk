"use client";

import {
  useCallback, useEffect, useReducer, useRef, useState, useSyncExternalStore, type ReactNode,
} from "react";

import { SERVICE_OK, getRepos, getStatus, pollQueue, postAsk, readService } from "../lib/api";
import { DEFAULT_REPO, FEATURED, repoAddress, repoFromSearch } from "../lib/featured";
import { safeGithubUrl } from "../lib/markdown";
import {
  BUSY_MESSAGE, BUSY_OVER_MESSAGE, IN_PROGRESS_MESSAGE, ON_ITS_OWN, SETTLING_MESSAGE,
  SET_LOADING_MESSAGE, WAITING_MESSAGE, canRetry, connectionNote, errorMessage, isAlarm, isQueued,
  loadingMessage, provenance, queuedAnnouncement, queuedMessage, serviceNote, setLoadFailedMessage,
} from "../lib/messages";
import {
  IDLE, askReducer, canSubmit, connectionReducer, serviceAfterAnswer, serviceAfterFailure,
  shouldRefreshService, type Ask,
} from "../lib/state";
import { DEFAULT_SET, loadSet, shownId } from "../lib/stored";
import type { AskResponse, Repo, Service, StoredSet } from "../lib/types";
import { Answer } from "./Answer";
import { Composer } from "./Composer";
import { CodeSheet, EvidencePanel } from "./EvidencePanel";
import { Header } from "./Header";
import { SuggestedQuestions } from "./SuggestedQuestions";

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
        The answer couldn’t be tied to lines in {repo}, so it isn’t shown. These files
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
function AskStatus({ ask, now, online, listShown, onRetry }: {
  ask: Ask;
  now: number;
  online: boolean;
  listShown: boolean; // the suggested questions are on screen below (Q54)
  onRetry: () => void;
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
      const waiting = ask.reason === "in_progress" ? IN_PROGRESS_MESSAGE : BUSY_MESSAGE;
      message = seconds > 0 ? waiting : BUSY_OVER_MESSAGE;
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
      // No "show the example" button (step 8, D2): the suggested questions stay on screen
      // below, and each one is a way back.
      const text = errorMessage(ask.failure, ask.repo, online, listShown);
      if (isAlarm(ask.failure, online)) alarm = <span className="text-error">{text}</span>;
      else message = <span>{text}</span>;
      if (canRetry(ask.failure)) {
        action = <RetryButton onClick={onRetry}>Try again</RetryButton>;
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
  // Suggested questions (Q54, step 8). `sets` caches each repo's loaded set; null = the repo
  // has none (composer only). `chosen`: the picked suggestion, null = the flagship.
  // `pendingRepo`: a switch waiting for its set's chunk; the page keeps the repo on screen
  // until it arrives, and if it fails, `setFailed` offers to try that same switch again.
  const [sets, setSets] = useState<Record<string, StoredSet | null>>(
    () => ({ [DEFAULT_SET.index.repo]: DEFAULT_SET }));
  const [chosen, setChosen] = useState<string | null>(null);
  const [pendingRepo, setPendingRepo] = useState<string | null>(null);
  const [setFailed, setSetFailed] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const lastSwitch = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const top = useRef<HTMLDivElement>(null); // the stored answer's label and its question
  const [now, setNow] = useState(0);
  // Are live questions open (Q45)? From every /status reply the page already makes and from
  // /ask; never polled while idle (Q14). lastStatusAt: when /status last answered.
  const [service, setService] = useState<Service>(SERVICE_OK);
  const lastStatusAt = useRef(0);
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
        if (result.ok) {
          setService(readService(result.data));
          lastStatusAt.current = Date.now();
        }
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
      setService(serviceAfterAnswer());
      dispatchAsk({ type: "response", requestId, response: result.data });
      return;
    }
    const at = Date.now();
    setNow(at);
    // Set together with the ask state, so the composer line and the question's own status never
    // show the same refusal, or neither (one owner per message, Q46 C7).
    setService((current) => serviceAfterFailure(current, result.failure));
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
        setService(result.service);
        lastStatusAt.current = Date.now();
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

  // A paused or daily-limit line may be stale when the visitor comes back to the tab hours
  // later: one /status fetch on return, only if it isn't ok and the last reply is over 60 s old
  // (step 8). Visitor-initiated, like a reload, so it is no keep-alive (Q14).
  useEffect(() => {
    if (service.status === "ok") return;
    function onVisible() {
      if (document.visibilityState !== "visible") return;
      if (!shouldRefreshService(service, lastStatusAt.current, Date.now())) return;
      lastStatusAt.current = Date.now(); // one fetch per return, even if it fails
      void getStatus(fetch, API).then((result) => {
        if (result.ok) setService(readService(result.data));
      });
    }
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [service]);

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

  function applyRepo(slug: string) {
    setPendingRepo(null);
    setRepo(slug);
    setChosen(null);
    setChosenN(null);
    setSheetOpen(false);
    dispatchAsk({ type: "switch_repo" }); // a live question in flight settles, never lands here
  }

  // Every switch takes a new id; only the latest may apply, so A -> B -> C ends on C and a late
  // B never overwrites it (step 8 review, item 2).
  function changeRepo(slug: string) {
    const id = ++lastSwitch.current;
    setSetFailed(null);
    if (slug === repo) {
      setPendingRepo(null); // back to the repo on screen: just cancel the pending switch
      return;
    }
    if (slug in sets) {
      applyRepo(slug);
      return;
    }
    setPendingRepo(slug);
    loadSet(slug).then(
      (result) => {
        if (id !== lastSwitch.current) return;
        setSets((current) => ({ ...current, [slug]: result.kind === "set" ? result.set : null }));
        applyRepo(slug);
      },
      () => {
        if (id !== lastSwitch.current) return;
        setPendingRepo(null); // the selector goes back to the repo whose content is on screen
        setSetFailed(slug);
      },
    );
  }

  // ?repo= (Q77). The page is static and opens on the default repo; the address is read once
  // after mount, and a featured repo it names is opened through the normal switch (its chunk
  // loads while the default stays on screen). From then on the address reflects the repo on
  // screen, never a pending one: replaceState only (no history entries, no back/forward), so an
  // unknown slug, a different spelling or a failed first load all end on the true address.
  const addressRead = useRef(false);
  useEffect(() => {
    if (!addressRead.current) {
      addressRead.current = true;
      const wanted = repoFromSearch(window.location.search) ?? DEFAULT_REPO;
      if (wanted !== repo) {
        // Syncing with the address, an external system the static page can't read at render.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        changeRepo(wanted);
        return; // the address is settled once that switch applies or fails
      }
    }
    if (pendingRepo !== null) return;
    const address = repoAddress(repo);
    if (window.location.pathname + window.location.search !== address) {
      window.history.replaceState(null, "", address);
    }
    // changeRepo is a fresh function each render; this runs when the repo on screen settles.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repo, pendingRepo]);

  function showStored(id: string) {
    setChosen(id);
    setChosenN(null);
    setSheetOpen(false);
    dispatchAsk({ type: "show_stored" });
    setFocusRequest((n) => n + 1);
  }

  // After every pick (the flagship too): bring the label and the question into view together
  // (round s5, F1), instantly when the visitor prefers reduced motion, and focus the heading
  // without letting the browser's focus scroll move the view (Q54). Runs after the render that
  // shows the new answer. Live answers don't scroll.
  useEffect(() => {
    if (focusRequest === 0 || !heading.current || !top.current) return;
    heading.current.focus({ preventScroll: true });
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    top.current.scrollIntoView({ block: "start", behavior: reduce ? "instant" : "smooth" });
  }, [focusRequest]);

  const openCitation = useCallback((n: number) => {
    setChosenN(n);
    if (!window.matchMedia(DESKTOP).matches) setSheetOpen(true);
  }, []);

  const set = sets[repo] ?? null;
  // The stored answer on screen: only while nothing live is (idle), so aria-current never marks
  // a live answer, even one whose text matches a suggestion (step 8 review, item 5).
  const storedId = set && ask.kind === "idle" ? shownId(set, chosen) : null;
  const example = storedId !== null && set ? set.answers[storedId] : undefined;
  const listShown = set !== null && ask.kind !== "loading" && ask.kind !== "waiting";
  const liveAnswer = ask.kind === "answered" || ask.kind === "ungrounded";
  const question = hasQuestion(ask) ? ask.question : example?.question;
  const response = ask.kind === "answered" ? ask.response : example?.response ?? null;
  const openN = chosenN ?? response?.citations.find((c) => c.valid)?.n ?? null;
  const online = typeof navigator === "undefined" || navigator.onLine;
  const panelShown = useSyncExternalStore(subscribeToWidth, sidePanelShown, () => false);
  const panel = <EvidencePanel response={response} openN={openN} onOpen={openCitation} />;

  // One owner per message (round 1, F4): connectionNote() decides, from the state, whether the
  // composer's connection line speaks. Only "down" is red; waking and offline are calm (F5).
  // The connection wins over the service line: while the server can't be reached, the page
  // can't know whether live questions are open.
  const connectionLine = connectionNote(connection, ask, now);
  const serviceLine = connection.kind === "up" ? serviceNote(service, ask, listShown) : null;
  // The set's chunk is about the page, not the server, so it comes after the connection line.
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
  ) : setFailed ? (
    <p className="text-text-muted">
      {setLoadFailedMessage(setFailed)}{" "}
      <button type="button" className="cursor-pointer underline"
              onClick={() => changeRepo(setFailed)}>
        Try again
      </button>
    </p>
  ) : pendingRepo ? (
    <p className="text-text-muted">{SET_LOADING_MESSAGE}</p>
  ) : serviceLine ? (
    <p className="text-text-muted">{serviceLine}</p>
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
            {/* A pick scrolls this block into view, so the stored answer's label is seen with
                its question (round s5, F1); focus goes to the heading (tabIndex -1, Q54). The
                header isn't sticky, so a small margin is enough. */}
            <div ref={top} className="scroll-mt-4">
              {example && <p className="mb-3 text-meta text-text-muted">{provenance(example)}</p>}
              <h1 id="question" ref={heading} tabIndex={-1}
                  className="font-serif text-title-sm font-medium text-balance lg:text-title">
                {question ?? `Ask a question about the code in ${repo}.`}
              </h1>
            </div>
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
              {liveAnswer && <p className="mt-4 text-meta text-text-muted">{ON_ITS_OWN}</p>}
              <AskStatus ask={ask} now={now} online={online} listShown={listShown} onRetry={retry} />
            </div>
            {listShown && set && (
              <SuggestedQuestions questions={set.index.questions} current={storedId}
                                  onPick={showStored} />
            )}
          </div>
          {/* While a switch waits for its set, the selector shows the new repo and Ask waits:
              a question must go to the repo whose answers are on screen. */}
          <Composer repo={pendingRepo ?? repo} repos={repos} onRepoChange={changeRepo} onAsk={submit}
                    canAsk={canSubmit(ask) && pendingRepo === null}
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
