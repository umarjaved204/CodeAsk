// The API contract, in one place (PLAN.md Q17). Mirrors backend/codeask/api/app.py.

export type Citation = {
  n: number;
  path: string;
  start: number;
  end: number;
  valid: boolean; // the cited lines lie inside the context the model was given
  url: string | null; // GitHub permalink at the indexed commit, only when valid
};

export type AskResponse = {
  answer: string; // plain text; the only links are server-made [n](cite:n) markers
  citations: Citation[];
  model: string;
  prompt_version: number;
};
