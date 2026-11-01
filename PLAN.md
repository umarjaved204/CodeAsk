# CodeAsk Plan

Status key: [ ] not started · [~] in progress · [x] done

## [ ] M0 Spike
One throwaway script: embed a small repo with Voyage → store in Neon pgvector → retrieve
chunks → answer with Groq, including one tool call. No UI.
Goal: prove every free tier works without a credit card; record rate limits and cold starts.

**Done when:** `ingest` and `ask` modes work; `ask` prints a Groq answer grounded in chunks
retrieved from Neon; tool tests A and B have each run ~5 times with results recorded; the
"M0 results" section below is filled in; and the Voyage decision rule has been applied to the
numbers.

### Voyage decision rule (written before measuring)
Voyage without a card is limited to 3 requests/min and 10K tokens/min. Decide from M0 results:
- **If** a typical small repo (≤ 30K tokens after file filtering) ingests in about 5 minutes
  **and** the demo test passes → go with **pre-indexed featured repos + small on-demand repos +
  file filtering + query-embedding cache**. Do **not** add a card.
- **If** the demo test fails → evaluate other free hosted embedding APIs (Gemini embedding
  models, Jina, Cohere trial) before considering a card. Their limits and terms are unverified:
  check them first.

**Demo test:** 4 query embeddings within 60 seconds (a simulated burst of demo users), counting
the 429s and recording the added wait per query.
- **Pass:** all 4 queries answered, worst added wait ≤ ~20 s, no errors.
- **Fail:** any error, or any wait > ~30 s.
- **Variant:** also run 6 queries in 60 s (the limit is shared across all visitors on one key)
  and record the actual waits.

## [ ] M1 Ingestion
Clone a GitHub repo, chunk the code (by function/class where possible), embed, store.

**Done when:** given a public repo URL, one command clones it, chunks it, embeds it and stores
it in Neon. Every chunk has its file path and start/end line numbers, and re-running on the
same repo doesn't create duplicates.

## [ ] M2 Basic RAG chat
Next.js chat UI + FastAPI endpoint; answers cite files and lines.

**Done when:** locally, I can paste a repo URL, ask a question in the browser, and get an
answer whose citations (file + line range) point to the correct code. The backend is deployed
to Render once, and its cold-start time is recorded here.

## [ ] M3 Eval harness
Question set with expected files; hit rate and MRR baseline.
Eval repo: a mid-sized repo I know well, **pinned to a specific commit SHA** so results are
reproducible. About **30 questions**, each with its known correct file(s).

**Done when:** one command runs retrieval over the ~30-question set on the pinned repo and prints
hit rate@k and MRR. The baseline numbers are recorded in this file.

## [ ] M4 Agent mode
Tools `search_code`, `read_file`, `list_dir`; LLM loops until it can answer.

**Done when:** agent mode works in the UI, and the eval harness reports agent vs plain RAG
side by side on the same question set, with the results recorded here. The comparison reports
**answer quality, hit rate, latency and LLM calls per question**. LLM calls matter because
Groq's free tier is rate-limited, so an agent that needs 6 calls per answer has a real cost.

## [ ] M5 Voice input
Browser Web Speech API, speech-to-text only, into the chat box.

**Done when:** in a supported browser, clicking a mic button fills the chat box with my
spoken question. In unsupported browsers the button is hidden or disabled.

## [ ] M6 Polish and deploy
Design pass, README with eval results, domain.

**Done when:** the app runs on Vercel + Render at my custom domain, and the README includes
the architecture, setup steps and the eval results table.

---

## M0 results
_Fill in during M0._

| Service | Signed up without card? | Free-tier limits (as documented) | Observed behaviour |
|---|---|---|---|
| Neon | | | |
| Voyage | | | |
| Groq | | | |
| Gemini | | | |

_Render cold start is measured in M2, when FastAPI is first deployed._

### Measurements
| Measurement | Result |
|---|---|
| Voyage: real tokens/min achieved during ingest | |
| Voyage: number of 429s during ingest | |
| Voyage: `Retry-After` header present on 429? | |
| Demo test (4 queries / 60 s): 429s, waits per query, pass/fail | |
| Demo variant (6 queries / 60 s): 429s, waits per query | |
| Neon: cold query time (after 5+ min idle) | |
| Neon: warm query time | |
| Groq: latency per call | |
| Groq: `x-ratelimit-*` headers | |
| Groq tool test A (forced): successful round-trips / runs | |
| Groq tool test B (auto, answer not in chunks): read_file called / runs | |
| Gemini works? | |

### Token counts after file filtering
| Repo | Files kept | Tokens | Est. ingest time at 10K TPM |
|---|---|---|---|
| itsdangerous | | | |
| | | | |
| | | | |
| | | | |

Notes:
