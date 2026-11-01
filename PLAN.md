# CodeAsk Plan

Status key: [ ] not started · [~] in progress · [x] done

## [~] M0 Spike
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
| Voyage: real tokens/min achieved during ingest | ~5,000 (itsdangerous source, 11,982 tokens, 5 requests of ≤3K, 143 s) |
| Voyage: number of 429s during ingest | 9K-token batches: first request 429'd 4/4 attempts over ~3 min (never accepted). 3K batches: 1 × 429, on the 4th request ~60 s after the 1st (not a clean 60 s sliding window) |
| Voyage: `Retry-After` header present on 429? | No |
| Demo test (4 queries / 60 s): 429s, waits per query, pass/fail | **PASS** (tight). Visitors at 0/15/30 s: 200. Visitor 4 at 45 s: 429, 429, then 200 at 62.5 s → waits 0/0/0/17.5 s, 2 × 429, 0 errors. Pattern = **3 requests per sliding ~60 s window** (requests 15 s apart were fine, so not 1 per 20 s); the 4th slot opens ~60 s after the 1st |
| Demo variant (6 queries / 60 s): 429s, waits per query | **FAIL**. Visitors at 0/10/20 s: 200. Visitors 4–6: 9 × 429; visitor 4 (first in the queue) used up all 4 attempts → error; visitor 5 waited 37.9 s, visitor 6 17.4 s. Rejected 429s don't seem to use a slot. Retry-with-backoff is **not first-come-first-served**: a later visitor took the slot that opened at ~60 s |
| Neon: cold query time (after 5+ min idle) | Connect 92.3 s / hang were **not** Neon: libpq stalled on the hostname's IPv6 addresses from my home network. Fixed in the spike by pinning IPv4 (`hostaddr`). Controlled test (5+ min idle): connect **2.06 s** vs 1.5–1.7 s warm, first query 0.25 s (same as warm). **Neon cold start ≈ 0.5 s**, negligible |
| Neon: warm query time | Connect 1.5–1.7 s (TLS + auth handshakes over a ~0.25 s round trip to Ohio). Simple query 0.25–0.31 s from home. Render → Neon in the same region should be milliseconds |
| Groq: latency per call | gpt-oss-120b: 1.2 s (first call, ~3K-token prompt) |
| Groq: `x-ratelimit-*` headers | gpt-oss-120b: 1,000 requests/day, **8,000 tokens/min**. One RAG prompt (~3K tokens) uses ~40% of a minute's budget; tool turns resend the whole history, so 429s came on the 2nd–3rd call. Groq **does** send `Retry-After` (11 s, 23 s) |
| Groq: gpt-oss-120b tool reliability (`ask`, 1 run) | 1 valid read_file call, then 3 invalid calls rejected by Groq: an invented `search` tool, then `read_file` with wrong argument names (`line_start`/`line_end`), even on the final turn with `tool_choice="none"`. No answer |
| Groq: qwen/qwen3.8-27b (`ask`, 1 run) | 1 valid read_file call, no invalid calls; full answer with accurate line-level citations (spot-checked against signer.py). Same 8,000 tokens/min; 2nd call needed 3 × 429 (~22 s) before succeeding. Latency 0.5 s / 1.6 s. Rerun after idle: identical answer, 0 × 429, but **one question with one tool turn used ~6,600 of the 8,000 tokens/min** → about 1 tool-using question per minute per model |
| Groq: models available (Nov 2026) | Chat + tools: only gpt-oss-120b, gpt-oss-20b, qwen3.8-27b. `llama-3.3-70b-versatile` no longer exists. Keep the model id in config |
| Groq tool test A (forced): successful round-trips / runs | gpt-oss-120b: **0/5**. Every run ignored the forced `tool_choice` and wrote a text answer (Groq rejected it); after error feedback it then made a valid read_file call. qwen3.8-27b: **5/5** clean (valid JSON, executor ran, answer returned) |
| Groq tool test B (auto, answer not in chunks): read_file called / runs | gpt-oss-120b: 0 correct in 2 complete runs (stopped manually in run 3). Sensible exploration (list_dir root, then the package), then read_file with **wrong argument names** (`line_start`/`line_end`) every time → no answer. qwen3.8-27b: **5/5 tool + correct**, 0 memorized, 0 wrong; read `url_safe.py` directly 5/5. Caveats: the 5 runs were identical (temperature 0 → this measures consistency, not a rate), and the question names "URL-safe", so finding the file was easy. Every run hit 429s (~1 run per minute) |
| Groq: qwen output-token limit | qwen3.8-27b also has **1,000 output tokens/min**. A request whose possible output exceeds it is rejected outright ("Request too large"), however long you wait. Fix: set `max_tokens` (now 600) and ask for answers under 250 words |
| Gemini works? | **Yes** (`gemini-flash-latest` replied "ok"), but took **148 s**, then **224 s** on a rerun, for a one-word reply. Repeatable, so not a one-off. Cause unknown (suspect the same IPv6 stall as Neon); must be fixed before the M3 eval |
| Retrieval sanity (itsdangerous, 5 questions, file-level) | hit@5 = 5/5, MRR@10 = 1.00. Easy questions that echo identifiers; top 5 often all from one file (overlapping near-duplicates) |

### Token counts after file filtering
Tokens after chunking (overlap included), counted locally with the voyage-code-3 tokenizer.

| Repo | Source tokens (files) | Tests tokens (files) | Docs tokens (files) | Total | Est. ingest at no-card limits |
|---|---|---|---|---|---|
| itsdangerous | 12,010 (10) | 4,281 (5) | 4,093 (9) | 20,384 | 2.0 min (source only 1.2) |
| psf/requests | 64,932 (22) | 19,721 (13) | 31,423 (20) | 116,076 | 11.6 min (source only 6.5) |
| pallets/flask | 98,412 (37) | 65,711 (46) | 122,914 (79) | 287,037 | 28.7 min (source only 9.8) |
| expressjs/express | 34,124 (50) | 138,188 (92) | 4,153 (3) | 176,465 | 17.6 min (source only 3.4) |
| umarjaved204/TableTalk | 185,846 (97) | 200,252 (78) | 67,768 (12) | 453,866 | 45.4 min (source only 18.6) |

Observations: only itsdangerous fits "≤ 30K tokens" with everything included. Source-only
filtering brings express (34K) close to it. Tests dominate express (78%) and TableTalk (44%);
docs dominate flask (43%). `.py` files outside the package (e.g. `docs/conf.py`) are counted as
source, a filter refinement for M1.

### Voyage decision rule, applied (proposed, awaiting my confirmation)
| Condition | Result |
|---|---|
| Small repo (≤ 30K tokens) ingests in ~5 min | Borderline: measured ~5K tokens/min, so 30K ≈ 6 min. A pacer with a few seconds of margin should reach ~9K tokens/min (≈ 3.5 min) |
| Demo test (4 queries / 60 s) | PASS (worst wait 17.5 s ≤ 20 s, no errors) |
| Variant (6 / 60 s, informational) | FAIL (1 error, 37.9 s wait) → bursts need a queue + cache |

**Outcome:** keep Voyage, no card. Design = pre-indexed featured repos + small on-demand repos +
file filtering + query-embedding cache, **plus a FIFO queue in the backend for Voyage calls**
(the 6/60 s test showed independent retries are unfair and can fail). Fallback if this proves
too slow: Gemini Embedding 1 (100 RPM / 30K TPM / 1,000 RPD).

### Other M0 decisions
- **LLM:** `qwen/qwen3.8-27b` (tool tests 10/10 clean vs gpt-oss-120b 0/5 + 0/2). Model id in config.
- **Groq budget:** 8K input + 1K output tokens/min per model → plain RAG (no tool turn, ~3K
  tokens) is the default in M2; set `max_tokens` and ask for short answers; agent turns in M4
  must be lean.
- **Neon:** cold start ≈ 0.5 s, a non-issue. Reuse connections (pooling) in M2. Locally, pin IPv4.
- **M2 context format:** prefix each line of retrieved chunks with its line number, so citations
  don't depend on the model counting lines.

### Fallback embedding candidates (free-tier limits as shown in dashboards)
| Option | RPM | TPM | RPD | Free pool | Notes |
|---|---|---|---|---|---|
| Voyage voyage-code-3, no card | 3 | 10K | – | 200M tokens | Code-specific. First 9K-token request 429'd 4× (no Retry-After) |
| Gemini Embedding 1 (AI Studio, free tier) | 100 | 30K | 1,000 | ongoing | General-purpose; free-tier data may be used by Google |

Notes:
