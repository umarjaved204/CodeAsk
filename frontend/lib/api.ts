// Talking to the API. Every outcome is classified, never thrown: the UI must tell "the server
// answered with an error" from "the server isn't there" (asleep on Render's free tier, down,
// or the visitor is offline). `fetch` is injected so the logic tests need no network.
import type { ApiErrorCode, AskResponse, Queue, Repo, Status } from "./types";

export type Failure =
  // The API answered with its JSON error shape (Q22).
  | {
      kind: "api";
      status: number;
      code: ApiErrorCode;
      message: string;
      requestId: string | null;
      retryAfterS: number | null; // from the Retry-After header (busy)
    }
  // No usable answer: the request failed, or the reply wasn't our JSON (e.g. Render's HTML page
  // while the instance wakes). The connection logic decides between waking, down and offline.
  | { kind: "unreachable" };

export type Result<T> = { ok: true; data: T } | { ok: false; failure: Failure };

type Fetch = typeof fetch;

const KNOWN_CODES = new Set<string>([
  "busy", "daily_cap", "model_unavailable", "database_unavailable", "timeout", "upstream_error",
  "internal_error", "not_found", "invalid_request", "method_not_allowed",
]);

function retryAfter(header: string | null): number | null {
  if (header === null || !/^\d+$/.test(header.trim())) return null;
  return Number(header.trim());
}

/** Turn a response into data or a classified failure. Pure apart from reading the body. */
export async function classify<T>(response: Response): Promise<Result<T>> {
  const isJson = (response.headers.get("content-type") ?? "").includes("application/json");
  let body: unknown;
  try {
    body = isJson ? await response.json() : undefined;
  } catch {
    body = undefined;
  }
  if (body === undefined) return { ok: false, failure: { kind: "unreachable" } };
  if (response.ok) return { ok: true, data: body as T };
  const error = body as Partial<Record<"error" | "message" | "request_id", unknown>>;
  return {
    ok: false,
    failure: {
      kind: "api",
      status: response.status,
      code: (KNOWN_CODES.has(String(error.error)) ? error.error : "error") as ApiErrorCode,
      message: typeof error.message === "string" ? error.message : "",
      requestId: typeof error.request_id === "string" ? error.request_id : null,
      retryAfterS: retryAfter(response.headers.get("retry-after")),
    },
  };
}

async function call<T>(fetchFn: Fetch, url: string, init?: RequestInit): Promise<Result<T>> {
  let response: Response;
  try {
    response = await fetchFn(url, init);
  } catch {
    return { ok: false, failure: { kind: "unreachable" } };
  }
  return classify<T>(response);
}

export function getStatus(fetchFn: Fetch, base: string, signal?: AbortSignal): Promise<Result<Status>> {
  return call<Status>(fetchFn, `${base}/status`, { cache: "no-store", signal });
}

/** The one place `queue` from /status is checked (Q40). Never throws: anything unexpected means
 *  "no queue", except a bad wait, which keeps the position and drops only the seconds. */
export function readQueue(raw: unknown): Queue | null {
  if (typeof raw !== "object" || raw === null) return null;
  const { position, wait_s: wait } = raw as Record<string, unknown>;
  if (typeof position !== "number" || !Number.isInteger(position) || position < 1 || position > 99) {
    return null;
  }
  const waitS = typeof wait === "number" && Number.isFinite(wait) && wait >= 0 ? wait : null;
  return { position, waitS };
}

/** Where the caller's question is in line, while it waits: a validated place, null when
 *  nothing is queued, or a failed poll (which the page ignores; the /ask reply decides). */
export async function pollQueue(fetchFn: Fetch, base: string, signal?: AbortSignal):
    Promise<{ ok: true; queue: Queue | null } | { ok: false }> {
  const result = await getStatus(fetchFn, base, signal);
  return result.ok ? { ok: true, queue: readQueue(result.data.queue) } : { ok: false };
}

export function getRepos(fetchFn: Fetch, base: string): Promise<Result<Repo[]>> {
  return call<Repo[]>(fetchFn, `${base}/repos`);
}

/** POST, never GET: a browser holds identical GETs behind a cache lock (M2-0). */
export function postAsk(fetchFn: Fetch, base: string, repo: string, question: string,
                        signal?: AbortSignal): Promise<Result<AskResponse>> {
  return call<AskResponse>(fetchFn, `${base}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo, question }),
    signal,
  });
}
