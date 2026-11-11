// What the page says about its own state (PLAN.md slice 3, state inventory). Pure, so the logic
// tests can pin the wording and the timing rules.
import type { Failure } from "./api";
import type { Ask, Connection } from "./state";
import type { Example, Grade, Queue, Service } from "./types";

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

// ---------- state 5, queued (Q40; wording: step 8) ----------

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

/** "Next in line" at position 2: true whether a question is ahead or only the rate limit holds
 *  this one (a lone visitor isn't "2nd"). From 3 on, the ordinal. */
function place(position: number): string {
  return position === 2 ? "Next in line" : `${ordinal(position)} in line`;
}

/** The visible line (aria-live off): it updates every poll, so the seconds stay current. The
 *  wait is an upper bound (the queue assumes the slowest recent answer), hence "up to". */
export function queuedMessage(queue: Queue): string {
  const where = place(queue.position);
  return queue.waitS === null ? `${where}.` : `${where}, up to about ${roundedWait(queue.waitS)} seconds.`;
}

/** The hidden live region's text: only the place, so it changes (and is announced) only when
 *  the position changes, never for the seconds. */
export function queuedAnnouncement(queue: Queue): string {
  return `${place(queue.position)}.`; // the visible line without the seconds
}

// ---------- slice 4: limits and the service line (Q45; step 8 decisions) ----------

/** "about N" for a wait: under an hour, up to the next 5 minutes; from an hour on, the nearest
 *  hour, at least 1 (step 8: rounding 61 minutes up to 2 hours overstated the wait by ~100%,
 *  and an early retry costs nothing). */
export function aboutTime(seconds: number): string {
  const minutes = Math.max(5, Math.ceil(seconds / 300) * 5);
  if (minutes < 60) return `about ${minutes} minutes`;
  const hours = Math.max(1, Math.round(seconds / 3600));
  return hours === 1 ? "about 1 hour" : `about ${hours} hours`;
}

// Said only when an example is actually on screen (step 8, decision 1): on load for a repo with
// an example, never in an /ask refusal, where the asked question has replaced it.
export const EXAMPLE_STILL_WORKS = "The example answer above still works.";
export const IN_PROGRESS_MESSAGE =
  "Your previous question is still being answered. Try again in a moment.";

function sentences(...parts: (string | false | null)[]): string {
  return parts.filter(Boolean).join(" ");
}

const tryAgain = (seconds: number | null) => seconds !== null && `Try again in ${aboutTime(seconds)}.`;
const tail = (exampleShown: boolean) => exampleShown && EXAMPLE_STILL_WORKS;

export function pausedMessage(exampleShown: boolean): string {
  return sentences("Live questions are paused right now.", tail(exampleShown));
}

export function dailyLimitMessage(retryAfterS: number | null, exampleShown: boolean): string {
  return sentences("Live questions are used up for now.", tryAgain(retryAfterS),
                   "This demo runs on a free API tier, so live questions are capped each day.",
                   tail(exampleShown));
}

export function perVisitorMessage(retryAfterS: number | null, exampleShown: boolean): string {
  return sentences("You’ve reached the daily limit of live questions for one visitor.",
                   tryAgain(retryAfterS), tail(exampleShown));
}

/** The composer's service line, or null when it is open or the question's own status already
 *  shows the same refusal (one owner per message, Q46 C7). The line follows `service`, so a
 *  refusal that changes it moves the line along, and returning to idle brings it back. */
export function serviceNote(service: Service, ask: Ask, exampleShown: boolean): string | null {
  if (service.status === "ok") return null;
  if (ask.kind === "error" && ask.failure.kind === "api" && ask.failure.code === service.status) {
    return null;
  }
  return service.status === "paused"
    ? pausedMessage(exampleShown)
    : dailyLimitMessage(service.retryAfterS, exampleShown);
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
    // A refusal replaces the example on screen, so these never add the example sentence.
    case "paused":
      return pausedMessage(false);
    case "daily_limit":
      return dailyLimitMessage(failure.retryAfterS, false);
    case "per_ip_limit":
      return perVisitorMessage(failure.retryAfterS, false);
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
// Limits and a removed repo: calm, and trying again can't help until they change.
const LIMITS = ["paused", "daily_limit", "per_ip_limit", "model_unavailable", "not_found"];

export function isAlarm(failure: Failure, online: boolean): boolean {
  if (failure.kind === "unreachable") return online;
  return !LIMITS.includes(failure.code);
}

/** The composer's connection line. One owner per message (round 1, F4): when the question
 *  itself failed for lack of a connection, its own status says so, and this line is quiet. */
export function connectionNote(connection: Connection, ask: Ask, now: number): string | null {
  if (ask.kind === "error" && ask.failure.kind === "unreachable") return null;
  return connectionMessage(connection, now);
}

/** Trying again can't help until the limit resets, the model returns or the repo list changes. */
export function canRetry(failure: Failure): boolean {
  return failure.kind === "unreachable" || !LIMITS.includes(failure.code);
}
