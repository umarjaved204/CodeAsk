// The API contract, in one place (PLAN.md Q17). Mirrors backend/codeask/ask.py public_view()
// and the error JSON of backend/codeask/api/app.py.

export type Citation = {
  n: number;
  path: string;
  start: number;
  end: number;
  valid: boolean; // the cited lines lie inside the context the model was given
  url: string | null; // GitHub permalink at the indexed commit, only when valid
  block: number | null; // index into AskResponse.blocks (Q30); null when unverified or capped
};

// A supplied context block that holds at least one valid citation: raw lines, exactly as the
// model saw them (Q30).
export type Block = { path: string; start: number; end: number; content: string };

export type RelevantFile = {
  path: string;
  start: number;
  end: number;
  url: string; // permalink to the file's best-ranked chunk: a retrieval suggestion
};

export type AskResponse = {
  grounded: boolean; // false = no valid citation: answer null, citations and blocks empty (Q23)
  answer: string | null; // markdown; the only links are server-made [n](cite:n) markers
  citations: Citation[];
  blocks: Block[];
  possibly_relevant: RelevantFile[]; // only when not grounded
  model: string;
  prompt_version: number;
};

// Error codes the API sends (Q22; slice 4: Q45, Q46 C6). The three 429s carry a whole-seconds
// Retry-After; paused (503) has none. tests/contract/backend-replies.json holds the real bodies.
export type ApiErrorCode =
  | "busy"
  | "paused" // the kill switch (503)
  | "daily_limit" // the day's token budget is spent, or Groq's own daily limit (429)
  | "per_ip_limit" // this visitor's questions for the last 24 h (429)
  | "in_progress" // this visitor's previous question is still running (429)
  | "model_unavailable"
  | "database_unavailable"
  | "timeout"
  | "upstream_error"
  | "internal_error"
  | "not_found"
  | "invalid_request"
  | "method_not_allowed"
  | "error";

export type ApiErrorBody = { error: string; message: string; request_id: string | null };

export type Status = {
  ok: boolean;
  model: string;
  model_available: boolean | null; // null = the model check itself failed (Q24)
  prompt_version: number;
  // The caller's own place in the /ask queue, found by their hashed IP (Q40, final in Q45).
  // Null when nothing of theirs is waiting. Never read directly: api.ts readQueue() checks it.
  queue?: unknown;
  // Whether live questions are open (Q45): "ok" | "paused" | "daily_limit", with
  // retry_after_s for daily_limit. Never read directly: api.ts readService() checks it.
  service?: unknown;
  retry_after_s?: unknown;
};

/** The queue's wire shape (app.py status()); used by the mocks. */
export type QueueWire = { position: number; wait_s: number | null };

/** A validated queue place: position 1 = being answered; waitS null = no usable estimate.
 *  waitS is an upper bound (the queue projects the slowest recent answer, Q46). */
export type Queue = { position: number; waitS: number | null };

/** A validated service state. retryAfterS: seconds from the reply, for daily_limit only. */
export type Service = { status: "ok" | "paused" | "daily_limit"; retryAfterS: number | null };

export type Repo = { slug: string; url: string };

export type Grade = {
  correct: string;
  grounded: string;
  citations_valid: string;
  // Slice 5 (Q51): pass and flagship are computed from these by `pregen export`, never stored.
  unsupported?: string;
  omission?: string;
  // Who checked it (Q37). One typed field, so the label can't contradict the record; who,
  // where and what is still pending goes in `note`, which the label never shows.
  reviewer: "claude" | "author";
  date: string;
  note: string;
};

// A stored answer (frontend/data/examples/<owner>__<name>/<id>.json, written by
// `pregen generate`; itsdangerous q1 is the slice 3 fixture, kept unchanged).
export type Example = {
  question_id?: string;
  question: string;
  repo: string;
  repo_url: string;
  commit_sha: string;
  generated_at: string; // ISO 8601, UTC
  model: string;
  prompt_version: number;
  grade: Grade | null; // "checked by the author" only when reviewer is "author"
  response: AskResponse;
};

// A repo's suggested questions, as `pregen export` writes them (index.json): passing answers
// only, flagship first (Q48).
export type StoredIndex = {
  repo: string;
  commit_sha: string;
  exported_at: string;
  flagship: string;
  flagship_note: string | null;
  questions: { id: string; question: string }[];
};

export type StoredSet = { index: StoredIndex; answers: Record<string, Example> };
