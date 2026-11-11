// What the page says about its own state (PLAN.md slice 3, state inventory). Pure, so the logic
// tests can pin the wording and the timing rules.
import type { Failure } from "./api";
import type { Ask, Connection } from "./state";
import type { Example, Grade, Queue } from "./types";

export const WAKING_SLOW_MS = 35_000;
export const LOADING_SLOW_MS = 12_000;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const CHECKED: Record<Grade["reviewer"], string> = {
  claude: " Checked against the cited code by Claude; not yet reviewed by the author.",
  author: " Checked by the author.",
};

export function provenance(example: Example): string {
  const date = new Date(example.generated_at); // UTC, so server and browser render the same text
  const day = `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
  const model = example.model.split("/").pop();
  const checked = !example.grade ? "" : CHECKED[example.grade.reviewer];
  return `Example answer, generated ${day} with ${model} on commit ` +
    `${example.commit_sha.slice(0, 7)}.${checked}`;
}

export function connectionMessage(connection: Connection, now: number): string | null {
  switch (connection.kind) {
    case "waking":
      return now - connection.since < WAKING_SLOW_MS
        ? "Waking up the server. This takes about 30 seconds after a quiet spell."
        : "Still starting. This is taking longer than usual.";
    case "down":
      return CANT_REACH_MESSAGE;
    case "offline":
      return OFFLINE_MESSAGE;
    default:
      return null;
  }
}

export function loadingMessage(elapsedMs: number): string {
  return elapsedMs < LOADING_SLOW_MS
    ? "Answering. This usually takes a few seconds."
    : "Still working. This demo is rate-limited, so it can take up to a minute.";
}

// ---------- state 5, queued (Q40, provisional) ----------

/** 1st, 2nd, 3rd, 4th … 11th, 12th, 13th … 21st, 22nd … 112th. */
export function ordinal(n: number): string {
  const lastTwo = n % 100;
  if (lastTwo >= 11 && lastTwo <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
}

/** A wait in seconds, rounded up to the next 10 and never 0: 1 -> 10, 40 -> 40, 41 -> 50. */
export function roundedWait(seconds: number): number {
  return Math.max(10, Math.ceil(seconds / 10) * 10);
}

/** The visible line (aria-live off): it updates every poll, so the seconds stay current. */
export function queuedMessage(queue: Queue): string {
  const place = `${ordinal(queue.position)} in line`;
  return queue.waitS === null ? `${place}.` : `${place}, about ${roundedWait(queue.waitS)} seconds.`;
}

/** The hidden live region's text: only the place, so it changes (and is announced) only when
 *  the position changes, never for the seconds. */
export function queuedAnnouncement(queue: Queue): string {
  return `${ordinal(queue.position)} in line.`; // the visible line without the seconds
}

/** Queued means someone is ahead: position 1 is being answered and reads as loading. */
export function isQueued(queue: Queue | null): queue is Queue {
  return queue !== null && queue.position >= 2;
}

// UI prose uses curly apostrophes (step 5, W9). Only the page's own wording: model answers and
// code-like strings (paths, cite: markers) are never touched. Tests that only need the message
// import these; tests that pin the wording keep it written out.
export const CANT_REACH_MESSAGE = "Can’t reach the server.";
export const OFFLINE_MESSAGE = "You’re offline. Check your connection and try again.";
export const DAILY_CAP_MESSAGE =
  "Today’s live questions are used up. The limit resets daily; the example answers still work.";

export function serverErrorMessage(requestId: string | null): string {
  return requestId
    ? `The server couldn’t answer (request ${requestId}). Try again.`
    : "The server couldn’t answer. Try again.";
}

export const WAITING_MESSAGE = "Your question will be sent when the server is ready.";
export const SETTLING_MESSAGE = "Finishing the previous question.";
export const BUSY_MESSAGE =
  "The demo is at capacity. This demo runs on free tiers, so only a few questions fit per minute.";
export const BUSY_OVER_MESSAGE = "You can try again now.";

export function errorMessage(failure: Failure, repo: string, online: boolean): string {
  if (failure.kind === "unreachable") {
    return online ? CANT_REACH_MESSAGE : OFFLINE_MESSAGE;
  }
  switch (failure.code) {
    case "daily_cap":
      return DAILY_CAP_MESSAGE;
    case "model_unavailable":
      return "Live answers are unavailable right now. The example answers still work.";
    case "not_found":
      return `${repo} is no longer available here.`;
    default:
      return serverErrorMessage(failure.requestId);
  }
}

/** Red and assertive only when something on our side failed: the server erred, or can't be
 *  reached while the visitor is online. Limits, a removed repo and the visitor's own offline
 *  network are calm (round 1, F5; offline: my decision). */
export function isAlarm(failure: Failure, online: boolean): boolean {
  if (failure.kind === "unreachable") return online;
  return !["daily_cap", "model_unavailable", "not_found"].includes(failure.code);
}

/** The composer's connection line. One owner per message (round 1, F4): when the question
 *  itself failed for lack of a connection, its own status says so, and this line is quiet. */
export function connectionNote(connection: Connection, ask: Ask, now: number): string | null {
  if (ask.kind === "error" && ask.failure.kind === "unreachable") return null;
  return connectionMessage(connection, now);
}

/** Trying again can't help until the limit resets, the model returns or the repo list changes. */
export function canRetry(failure: Failure): boolean {
  return failure.kind === "unreachable" ||
    !["daily_cap", "model_unavailable", "not_found"].includes(failure.code);
}
