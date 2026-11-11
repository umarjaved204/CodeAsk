// What the page says about its own state (PLAN.md slice 3, state inventory). Pure, so the logic
// tests can pin the wording and the timing rules.
import type { Failure } from "./api";
import type { Connection } from "./state";
import type { Example, Grade } from "./types";

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
      return "Can't reach the server.";
    case "offline":
      return "You're offline. Check your connection and try again.";
    default:
      return null;
  }
}

export function loadingMessage(elapsedMs: number): string {
  return elapsedMs < LOADING_SLOW_MS
    ? "Answering. This usually takes a few seconds."
    : "Still working. This demo is rate-limited, so it can take up to a minute.";
}

export const WAITING_MESSAGE = "Your question will be sent when the server is ready.";
export const SETTLING_MESSAGE = "Finishing the previous question.";
export const BUSY_MESSAGE =
  "The demo is at capacity. This demo runs on free tiers, so only a few questions fit per minute.";
export const BUSY_OVER_MESSAGE = "You can try again now.";

export function errorMessage(failure: Failure, repo: string, online: boolean): string {
  if (failure.kind === "unreachable") {
    return online ? "Can't reach the server." : "You're offline. Check your connection and try again.";
  }
  switch (failure.code) {
    case "daily_cap":
      return "Today's live questions are used up. The limit resets daily; the example answers still work.";
    case "model_unavailable":
      return "Live answers are unavailable right now. The example answers still work.";
    case "not_found":
      return `${repo} is no longer available here.`;
    default:
      return failure.requestId
        ? `The server couldn't answer (request ${failure.requestId}). Try again.`
        : "The server couldn't answer. Try again.";
  }
}

/** Trying again can't help until the limit resets, the model returns or the repo list changes. */
export function canRetry(failure: Failure): boolean {
  return failure.kind === "unreachable" ||
    !["daily_cap", "model_unavailable", "not_found"].includes(failure.code);
}
