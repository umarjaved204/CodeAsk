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

// Error codes the API sends (Q22). "daily_cap" is provisional until slice 4 builds the cap.
export type ApiErrorCode =
  | "busy"
  | "daily_cap"
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
};

export type Repo = { slug: string; url: string };

export type Grade = {
  correct: string;
  grounded: string;
  citations_valid: string;
  by: string;
  date: string;
  author_checked: boolean; // false: graded by Claude, the author's spot-check is still pending
  note: string;
};

// A pre-generated answer (frontend/data/examples/*.json, written by `ask --save`).
export type Example = {
  question: string;
  repo: string;
  repo_url: string;
  commit_sha: string;
  generated_at: string; // ISO 8601, UTC
  model: string;
  prompt_version: number;
  grade: Grade | null; // "checked by the author" only when author_checked is true
  response: AskResponse;
};
