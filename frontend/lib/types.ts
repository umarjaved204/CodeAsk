// The API contract, in one place (PLAN.md Q17). Mirrors backend/codeask/api/app.py.

export type Citation = {
  n: number;
  path: string;
  start: number;
  end: number;
  valid: boolean; // the cited lines lie inside the context the model was given
  url: string | null; // GitHub permalink at the indexed commit, only when valid
};

export type RelevantFile = {
  path: string;
  start: number;
  end: number;
  url: string; // permalink to the file's best-ranked chunk: a retrieval suggestion
};

export type AskResponse = {
  grounded: boolean; // false = no valid citation: answer is null, citations empty (Q23)
  answer: string | null; // plain text; the only links are server-made [n](cite:n) markers
  citations: Citation[];
  possibly_relevant: RelevantFile[]; // only when not grounded
  model: string;
  prompt_version: number;
};
