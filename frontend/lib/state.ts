// The page's two small state machines (PLAN.md Q34), as pure reducers with discriminated
// unions. Time always arrives in the event (`at`, ms), never from Date.now(), so the logic
// tests can drive them. Everything else in the state inventory (the example answer, waking
// phases, long answers, truncation, input limits) is a rendering condition, not a state.
import type { Failure } from "./api";
import type { AskResponse, Queue } from "./types";

// ---------- connection: is the API there? ----------
// A free Render instance sleeps after 15 min idle and takes ~30 s to wake (M2-0), so "no
// answer yet" means waking for a while before it means down.
export const WAKING_GIVE_UP_MS = 90_000;

export type Connection =
  | { kind: "unknown" } // nothing heard yet
  | { kind: "waking"; since: number } // no answer since `since`; still within the window
  | { kind: "up" }
  | { kind: "down" } // no answer for the whole waking window
  | { kind: "offline" }; // the browser itself has no network

export type ConnectionEvent =
  | { type: "status_ok" }
  | { type: "status_failed"; at: number; online: boolean }
  | { type: "retry"; at: number }; // the visitor asks to try again after "down"

export function connectionReducer(state: Connection, event: ConnectionEvent): Connection {
  switch (event.type) {
    case "status_ok":
      return { kind: "up" };
    case "status_failed": {
      if (!event.online) return { kind: "offline" };
      const since = state.kind === "waking" ? state.since : event.at;
      if (state.kind === "down") return state;
      return event.at - since >= WAKING_GIVE_UP_MS ? { kind: "down" } : { kind: "waking", since };
    }
    case "retry":
      return { kind: "waking", since: event.at };
  }
}

// ---------- ask lifecycle: one question at a time ----------
type Asked = { repo: string; question: string };

export type Ask =
  // Nothing asked (the page shows the repo's example, if it has one). `settling` holds the id
  // of a request still in flight for a repo the visitor left: Ask stays disabled until it
  // settles, because slice 4 allows one question in flight per visitor.
  | { kind: "idle"; settling: number | null }
  // Submitted while the server is waking: sent once, automatically, when it is up.
  | ({ kind: "waiting" } & Asked)
  // `queue` is the question's place in line while it waits (state 5, Q40: data on loading, not
  // a state of its own). `startedAt` drives the "Still working…" escalation and restarts when
  // the question reaches the front from further back.
  | ({ kind: "loading"; requestId: number; startedAt: number; queue: Queue | null } & Asked)
  | ({ kind: "answered"; response: AskResponse } & Asked)
  | ({ kind: "ungrounded"; response: AskResponse } & Asked)
  | ({ kind: "busy"; retryAt: number } & Asked) // 503 busy: manual retry after Retry-After
  | ({ kind: "error"; failure: Failure } & Asked);

export type AskEvent =
  | { type: "submit"; repo: string; question: string; requestId: number; at: number;
      serverUp: boolean }
  | { type: "send"; requestId: number; at: number } // the waiting question goes out
  | { type: "response"; requestId: number; response: AskResponse }
  | { type: "failure"; requestId: number; failure: Failure; at: number }
  | { type: "queue_update"; requestId: number; queue: Queue | null; at: number } // a /status poll
  | { type: "switch_repo" };

export const IDLE: Ask = { kind: "idle", settling: null };
const BUSY_DEFAULT_RETRY_S = 60;

/** Ask is disabled while a question is loading, waiting, or still settling after a switch. */
export function canSubmit(state: Ask): boolean {
  return state.kind !== "loading" && state.kind !== "waiting" &&
    !(state.kind === "idle" && state.settling !== null);
}

export function askReducer(state: Ask, event: AskEvent): Ask {
  switch (event.type) {
    case "submit": {
      if (!canSubmit(state)) return state; // e.g. Enter while loading does nothing
      const asked = { repo: event.repo, question: event.question };
      return event.serverUp
        ? { kind: "loading", requestId: event.requestId, startedAt: event.at, queue: null, ...asked }
        : { kind: "waiting", ...asked };
    }
    case "send":
      if (state.kind !== "waiting") return state;
      return { kind: "loading", requestId: event.requestId, startedAt: event.at, queue: null,
               repo: state.repo, question: state.question };
    case "queue_update": {
      if (state.kind !== "loading" || state.requestId !== event.requestId) return state; // stale
      // Restart the escalation clock only when the question reaches the front from further
      // back: a question that never showed a queue keeps its clock (Q40).
      const reachedFront = (state.queue?.position ?? 0) >= 2 && event.queue?.position === 1;
      return { ...state, queue: event.queue, startedAt: reachedFront ? event.at : state.startedAt };
    }
    case "switch_repo":
      if (state.kind === "loading") return { kind: "idle", settling: state.requestId };
      if (state.kind === "idle") return state;
      return IDLE;
    case "response":
    case "failure": {
      // The old repo's request settled: drop its result, re-enable Ask.
      if (state.kind === "idle" && state.settling === event.requestId) return IDLE;
      // Anything else that isn't the current request is stale.
      if (state.kind !== "loading" || state.requestId !== event.requestId) return state;
      const asked = { repo: state.repo, question: state.question };
      if (event.type === "response") {
        return event.response.grounded
          ? { kind: "answered", response: event.response, ...asked }
          : { kind: "ungrounded", response: event.response, ...asked };
      }
      const f = event.failure;
      if (f.kind === "api" && f.code === "busy") {
        return { kind: "busy", retryAt: event.at + (f.retryAfterS ?? BUSY_DEFAULT_RETRY_S) * 1000,
                 ...asked };
      }
      return { kind: "error", failure: f, ...asked };
    }
  }
}
