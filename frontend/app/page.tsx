"use client";

// M2 slice 1: a bare page. The answer is rendered as plain text (React escapes it), and only
// server-made [n](cite:n) markers become chips. Chip links come from the citations list,
// never from the answer text. Markdown rendering arrives in slice 3.
import { useState, type FormEvent, type ReactNode } from "react";
import type { AskResponse, Citation } from "../lib/types";

const API = process.env.NEXT_PUBLIC_API_URL;
const CITE = /\[(\d+)\]\(cite:\1\)/g;

function Chip({ citation, n }: { citation?: Citation; n: string }) {
  const label = citation ? `${citation.path}:${citation.start}-${citation.end}` : "unknown";
  if (citation?.valid && citation.url?.startsWith("https://github.com/")) {
    return (
      <a href={citation.url} target="_blank" rel="noopener noreferrer" title={label}>
        [{n}]
      </a>
    );
  }
  return (
    <span title={`unverified: ${label}`} style={{ color: "#888" }}>
      [{n}?]
    </span>
  );
}

function renderAnswer(answer: string, citations: Citation[]): ReactNode[] {
  const byN = new Map(citations.map((c) => [String(c.n), c]));
  const parts: ReactNode[] = [];
  let last = 0;
  for (const m of answer.matchAll(CITE)) {
    parts.push(answer.slice(last, m.index));
    parts.push(<Chip key={m.index} n={m[1]} citation={byN.get(m[1])} />);
    last = m.index + m[0].length;
  }
  parts.push(answer.slice(last));
  return parts;
}

export default function Home() {
  const [repo, setRepo] = useState("pallets/itsdangerous");
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState("");
  const [result, setResult] = useState<AskResponse | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setStatus("Asking…");
    setResult(null);
    try {
      const res = await fetch(`${API}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo, question }),
      });
      if (!res.ok) {
        setStatus(`Error ${res.status}`);
        return;
      }
      setResult((await res.json()) as AskResponse);
      setStatus("");
    } catch {
      setStatus("Could not reach the server.");
    }
  }

  return (
    <main>
      <h1>CodeAsk</h1>
      <form onSubmit={submit}>
        <input value={repo} onChange={(e) => setRepo(e.target.value)} aria-label="Repository" />
        <br />
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={400}
          rows={3}
          cols={60}
          aria-label="Question"
          placeholder="Ask about the code"
        />
        <br />
        <button type="submit" disabled={!question.trim()}>
          Ask
        </button>
      </form>
      <p aria-live="polite">{status}</p>
      {result && (
        <section>
          {result.answer === null ? (
            <>
              <p>Couldn&apos;t ground this in the code. Possibly relevant files:</p>
              <ul>
                {result.possibly_relevant.map((f) => (
                  <li key={f.path}>
                    <a href={f.url} target="_blank" rel="noopener noreferrer">
                      {f.path}:{f.start}-{f.end}
                    </a>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p style={{ whiteSpace: "pre-wrap" }}>{renderAnswer(result.answer, result.citations)}</p>
          )}
          <ol>
            {result.citations.map((c) => (
              <li key={c.n} value={c.n}>
                <Chip citation={c} n={String(c.n)} /> {c.path}:{c.start}-{c.end}
                {!c.valid && " (unverified)"}
              </li>
            ))}
          </ol>
          <small>
            {result.model}, prompt v{result.prompt_version}. Each question is answered on its own.
          </small>
        </section>
      )}
    </main>
  );
}
