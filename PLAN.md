# CodeAsk Plan

Status key: [ ] not started · [~] in progress · [x] done

## [x] M0 Spike
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
Clone a GitHub repo, chunk the code by syntax (functions/classes) where possible, embed, store.
Designed in a grilling session (3 rounds, 2026-11-01) with mentor review; decisions below.

**Done when:**
1. `python -m codeask.ingest <github-url> [--ref <sha>] [--tests] [--docs] [--yes]` clones
   (shallow), filters, chunks (tree-sitter for Python/JS/TS, fixed windows otherwise), embeds
   and stores in Neon. Every chunk has a path, 1-based inclusive start/end lines, kind,
   breadcrumb and category.
2. Re-running on the same ref makes **0 Voyage requests** and creates no duplicate rows.
   **A body edit inside one unit changes exactly one hash** (so exactly 1 new embedding).
3. **Interruption test (manual):** Ctrl+C mid-ingest → `search` still serves the old index →
   a re-run resumes from the cached embeddings.
4. `pytest` passes the test list below (the slow real-tokenizer test runs with `-m slow`).
5. `python -m codeask.search <repo> "<question>"` prints the top 5 with distance, kind,
   breadcrumb and path:lines. On itsdangerous, the 5 M0 sanity questions each have their
   expected file in the top 5 (a regression check, not an eval).
6. This file records the ingest summaries for itsdangerous and express (source only):
   per-category chunks and tokens, chunk-size distribution (mean, median, p95 tokens),
   fallback files, skipped files with reasons (including the "line exceeds cap" count), and the
   measured tokens/min.

### M1 task list (build order)
1. **Skeleton:** root `pyproject.toml` (editable install, package in `backend/codeask/`, pytest
   config), pinned `requirements.txt`, `requirements-dev.txt` (pytest). `pytest` runs from the
   repo root.
2. **tree-sitter smoke test:** parse one Python, JS, TS and TSX file and print the node-type
   names; record them here. If tree-sitter-typescript 0.23.2 won't load with tree-sitter 0.26,
   pin the newest tree-sitter that works.
3. **File filters** + tests (skip rules, categories, per-file reasons).
4. **Python chunker** + tests + the real-corpus sweep over the 5 cloned repos.
5. **`count` command.** Compare with the M0 table: expect ~15–20% fewer tokens, because the
   10-line overlap is gone.
6. **Vertical slice on itsdangerous (Python only):** schema + store (`repos`, `chunks`,
   `embeddings`; drop `m0_chunks`) → embedder + shared limiter → `ingest` CLI (clone with
   `--ref`, ETA + confirm, embed with a commit per batch, transactional swap, summary) + `gc` →
   `search`. Run it; re-run (0 requests); interruption test; sanity questions; measure
   tokens/min.
7. **JS/TS chunker** (named units from the step 2 node names, export wrappers, const arrow
   functions, Express callbacks) + tests + corpus sweep.
8. **README splitter** + tests; **fixed-window fallback** polish (other languages, parse
   errors) + tests.
9. **Real runs:** express (source) and a re-run of itsdangerous; record the summaries.
10. **Record** the results here and commit.

### M1 decision log
| Decision | Why | Rejected alternative |
|---|---|---|
| Embedding key = `sha256(space + embed_text)`, space = `voyage-code-3:1024:document` | Keyed on exactly what is embedded: changing a flag or model re-embeds automatically, and line shifts change nothing | M0 key with repo/path/start_line (inserting one line re-embedded the rest of the file) |
| Schema: `repos`, `chunks` (per repo), `embeddings(content_hash, space, token_count, vector)` shared across repos | Switching models needs no re-chunking; identical code shares one vector | Vector column on `chunks` |
| Orphaned embeddings kept; removed only by `gc` and on repo deletion (unreferenced only) | Switching back to a variant costs only chunking time; ~0.8 MB per 60K-token variant | Deleting orphans on every re-ingest |
| One active chunk set per repo; settings (including chunker and grammar versions) in `repos.settings`; M3 snapshots the settings with each result | No variant filter on every query; results stay reproducible | `variant` column with several live sets |
| Ingest = embed first (commit per batch), then swap chunk rows + `repos` row in **one transaction** | An interrupted ingest leaves the old index live; a re-run resumes from the cache | Delete-then-insert |
| Shallow clone; `--ref <sha>` via `git fetch --depth 1 origin <sha>`; `-c core.autocrlf=false`; Windows-safe deletion (read-only .git files) | M3 commit pinning; stable hashes | Full clone |
| Normalize CRLF→LF and strip a BOM, in memory only; strict UTF-8, else skip with "not UTF-8" | Same hashes on Windows and Render; odd files are visible | `errors="replace"` (silent U+FFFD) |
| tree-sitter, individual pinned grammar packages: Python, JS, TS, TSX. `.py`; `.js .jsx .mjs .cjs`; `.ts .mts .cts`; `.tsx`; `.d.ts` excluded (takes precedence over `.ts`) | Multi-language, error-tolerant, one API; prebuilt wheels for Windows + Python 3.13 | Python `ast` (Python only); tree-sitter-language-pack (~170 grammars) |
| Parse errors: whole-file fallback to fixed windows if `root.has_error`; fallback count reported | Simple; grammar gaps become measurable | Per-unit fallback |
| Units: every top-level node. Named units per language (Python: function/class/decorated_definition; TS/JS: function/class declarations, export wrappers, const arrow functions or function expressions, interface/type/enum) | One rule; covers Express-style top-level calls | Gap collection (functions/classes + "module" leftovers) |
| Merge only units below the min, stop at the target, like with like (anonymous with anonymous, small named siblings together); units that share a line must merge | Fewer tiny chunks without mixing unrelated code; keeps "one chunk per line" exact | Greedy merge of anything adjacent |
| Leading comments: only contiguous comment lines directly above a unit attach | Matches how doc comments are written | All comments since the previous unit |
| Class over the max: header chunk (own lines + **capped** method-signature outline in `embed_text`, counted toward the cap) + method chunks | "What can X do?" matches the header | Header without an outline |
| Function over the max: split at top-level statements; recurse into compound statements and into call arguments → callback bodies (with the call's first line as context); then line windows; **never oversize**. Each piece carries the signature | The hard cap stays strict; Express callbacks get real chunks | Oversized chunks |
| A line over the token cap: skip the file (measured with the real tokenizer; the character rule is a cheap pre-filter); count reported. If it drops meaningful files, revisit by truncating that line in `embed_text` only | "No chunk exceeds the max" is true by construction | Cutting lines by characters (breaks citations and coverage) |
| Budgets (Voyage tokens, measured on `embed_text`, in config): target 200–500, max 800, min 60 | Top 5 × 800 = 4K tokens fits Groq's 8K tokens/min | 300–800 / 1,200 / 80 (top 5 = 6K) |
| `embed_text` = `File: <path>\nScope: <breadcrumb>\n\n<code>`; flags `embed_include_path` and `embed_include_scope` | Adds the context raw code lacks; M3 can ablate each part | A `Language:` line; a natural-language prefix |
| No overlap between chunks | The coverage invariant is exact; no near-duplicates | 10-line overlap (M0) |
| README: line scanner with fence state; split at `#`/`##` outside fences; merge to the target; paragraph → sentence fallback for over-cap sections; skip image/badge-only lines | Headings are the document's semantic boundaries; example code is never cut | Markdown grammar; fixed windows |
| Default categories: source + root README; `--tests` and `--docs` flags; category on every chunk | Embedding is the scarce resource; M3 measures what tests and docs add | Ingest everything |
| Skip rules: first-5-lines markers (`@generated`, `do not edit`, `auto-?generated`, `generated by`, `code generated`); `*.gen.*`, `*_pb2.py`, `*.pb.go`, `*.d.ts`, lockfiles; code with max line > ~1,500–2,000 chars or average > 200 (not markdown); `migrations/`, `alembic/versions/`, `fixtures/` (directory), `docs/conf.py`; empty files. Reasons printed per file | TableTalk inspection: one generated file, longest real line 196 chars | Skipping `components/ui/`; a smaller size cap (would drop real 32 KB modules) |
| Pacer: shared in-process limiter with a priority/reserved-slots parameter (unused in M1); 3 requests per 60 + 5 s window; ≤ 3K tokens per batch; 3 retries | Fixes M0's 429s; ready for M2's query priority | Independent per-call retries |
| Code: `backend/codeask/` package, `python -m` entry points, root `pyproject.toml` editable install; spike/m0.py frozen | M2 imports the same code; M0 stays reproducible | A second spike script |
| `search` CLI in M1 | Proves an ingest retrieves, not just that rows exist | Leaving retrieval to M2 |

**Limitation:** the limiter is in-process and doesn't coordinate across processes. Don't run
CLI ingestion while the live app uses the same Voyage key (revisit in M2).

### M1 tests (pytest, fake token counter unless marked)
- **Coverage:** every non-blank line is in exactly one chunk, including units that share a line.
- **Line numbers:** stored ranges are 1-based inclusive (tree-sitter rows are 0-based), and
  `file_lines[start-1:end]` equals the chunk content.
- **Cap:** no chunk exceeds the max; a file with an over-cap line is skipped.
- **Determinism:** two runs give identical output; CRLF and LF input give identical hashes.
- **Stability:** a body edit inside one unit changes exactly one hash; inserting lines above a
  unit changes no other unit's hash.
- **Fallback:** a syntax error falls back to windows; an empty or whitespace-only file gives no
  chunks.
- **Express:** a callback inside `app.get(...)` is recursed into and carries the call's first
  line.
- **Classes:** a class over the max splits into a header + methods; the outline cap holds.
- **README:** fences are never split; headings inside fences are ignored.
- **Filters:** one sample file per skip rule.
- **Edge cases:** single-unit file, no trailing newline, comments-only file, `.d.ts` precedence
  over the `.ts` mapping, the like-with-like merge rule.
- **Real-corpus sweep:** run the chunker over the 5 cloned repos and assert coverage, the cap
  and `file_lines[start-1:end] == content` on every file.
- **Slow (`-m slow`):** one test with the real Voyage tokenizer.
- Sample files live in `backend/tests/samples/` (not `fixtures/`, which our own skip rule
  excludes).

### Not in M1 (scope guard)
Reranking, summaries, call graphs, languages beyond Python/JS/TS, the web UI, per-unit parse
fallback, a cross-process limiter.

## [ ] M2 Basic RAG chat
Next.js chat UI + FastAPI endpoint; answers cite files and lines.

**Done when:** locally, I can paste a repo URL, ask a question in the browser, and get an
answer whose citations (file + line range) point to the correct code. The backend is deployed
to Render once, and its cold-start time is recorded here.

### M2 inputs (requirements collected in M0 and the M1 grilling)
**Context building**
- Number every line of the retrieved chunks with its **absolute file line number** (not 1..n per
  chunk), so citations don't depend on the model counting lines.
- **Token-budget context packing:** fill the context up to ~3K tokens instead of a fixed k=5
  (Groq: 8K tokens/min per model).
- **Class header chunks:** when one is retrieved, build the method outline from its child chunk
  rows (names and line ranges) and include it in the context, so the model sees what matched.
- **Near-duplicates:** M0's top 5 were often all from one file. Merge adjacent chunks from the
  same file into one context block, and consider a per-file cap. Decide in M2.

**Voyage queue and pacer** (see "Capacity" under M0 results)
- Bounded FIFO queue; respond "busy, try again" when the estimated wait exceeds ~45 s; show the
  queue position in the UI.
- Queries have priority over ingestion: use the limiter's reserved-slots parameter so ingestion
  takes at most 2 of the 3 slots per window.
- Query-embedding cache, plus pre-cached embeddings for the suggested questions on featured
  repos.
- The M1 limiter is in-process only. Don't run CLI ingestion while the live app uses the same
  key, or make the limiter coordinate across processes.

**Deployment**
- Pick Render's **Ohio** region, next to Neon (US East 2), so DB round trips are milliseconds.
- Reuse DB connections (pooling).

## [ ] M3 Eval harness
Question set with expected files; hit rate and MRR baseline.
Eval repo: **small in tokens** (about **60K tokens or less** after filtering), **pinned to a
specific commit SHA** so results are reproducible. About **30 questions**, each with its known
correct file(s).
- Why small: every variant (chunking strategy, tests/docs on or off, embedding model) needs a
  full re-embed at 3 requests/min, so a 60K repo costs ~7–12 min per variant.
- It should be a repo the model has **not memorized**, ideally one I know well (so I can write
  questions with known answers).
- TableTalk is 454K tokens (186K source). Inspected 2026-11-01: nothing is inflated. It's 658 KB
  of real, heavily documented code (~3.5 bytes/token), with one small generated file. The whole
  repo is too big, but a subset could fit (e.g. `src/tabletalk/model` + `simulation` +
  `evaluation` ≈ 145 KB ≈ 41K tokens). I know it well, and the model hasn't memorized it.
- Each result records the `repos.settings` snapshot (chunker, grammar versions, flags).
- The M0 sanity result (5/5, MRR 1.0) shows the naive baseline is **saturated** on
  itsdangerous with easy questions, so it can't distinguish chunking strategies. The eval needs
  harder questions (no echoed identifiers) on a less trivial repo.
- Embedding comparison: Voyage voyage-code-3 vs **Gemini Embedding** (see the decision below).

**Done when:** one command runs retrieval over the ~30-question set on the pinned repo and prints
hit rate@k and MRR. The baseline numbers are recorded in this file.

## [ ] M4 Agent mode
Tools `search_code`, `read_file`, `list_dir`; LLM loops until it can answer.

**Done when:** agent mode works in the UI, and the eval harness reports agent vs plain RAG
side by side on the same question set, with the results recorded here. The comparison reports
**answer quality, hit rate, latency and LLM calls per question**. LLM calls matter because
Groq's free tier is rate-limited, so an agent that needs 6 calls per answer has a real cost.

Notes from M0:
- The M0 tool-test results are **not a reliability rate**. qwen's 5/5 is one sample repeated
  5 times (temperature 0, and the question names "URL-safe"). The real rate comes from running
  the ~30 different M3 questions.
- Agent mode runs at ~1 question/min live (Groq 8K tokens/min). Decide in M4 whether it is a
  **live feature** or an **eval/replay feature** (pre-recorded runs shown in the UI).

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

Ingest estimates (all / source only). **Correction:** the original estimates assumed the
documented 10K tokens/min, which is never reached. Measured throughput was **~5K tokens/min**
(partly due to the 429 stall). With a pacer that adds a few seconds of margin, real throughput
is probably **~8–9K tokens/min** (3 requests × ≤3K tokens). That must be re-measured in M1.

| Repo | Source tokens (files) | Tests tokens (files) | Docs tokens (files) | Total | Ingest at 5K/min (measured) | Ingest at ~8.5K/min (with margin, to verify) |
|---|---|---|---|---|---|---|
| itsdangerous | 12,010 (10) | 4,281 (5) | 4,093 (9) | 20,384 | 4.1 min (source 2.4) | 2.4 min (source 1.4) |
| psf/requests | 64,932 (22) | 19,721 (13) | 31,423 (20) | 116,076 | 23.2 min (source 13.0) | 13.7 min (source 7.6) |
| pallets/flask | 98,412 (37) | 65,711 (46) | 122,914 (79) | 287,037 | 57.4 min (source 19.7) | 33.8 min (source 11.6) |
| expressjs/express | 34,124 (50) | 138,188 (92) | 4,153 (3) | 176,465 | 35.3 min (source 6.8) | 20.8 min (source 4.0) |
| umarjaved204/TableTalk | 185,846 (97) | 200,252 (78) | 67,768 (12) | 453,866 | 90.8 min (source 37.2) | 53.4 min (source 21.9) |

Observations: only itsdangerous fits "≤ 30K tokens" with everything included. Source-only
filtering brings express (34K) close to it. Tests dominate express (78%) and TableTalk (44%);
docs dominate flask (43%). `.py` files outside the package (e.g. `docs/conf.py`) are counted as
source, a filter refinement for M1.

### Voyage decision rule, applied (confirmed 2026-11-01)
| Condition | Result |
|---|---|
| Small repo (≤ 30K tokens) ingests in ~5 min | Borderline: measured ~5K tokens/min, so 30K ≈ 6 min. A pacer with a few seconds of margin should reach ~9K tokens/min (≈ 3.5 min) |
| Demo test (4 queries / 60 s) | PASS (worst wait 17.5 s ≤ 20 s, no errors) |
| Variant (6 / 60 s, informational) | FAIL (1 error, 37.9 s wait) → bursts need a queue + cache |

**Outcome:** keep Voyage, no card. Design = pre-indexed featured repos + small on-demand repos +
file filtering + query-embedding cache, **plus a FIFO queue in the backend for Voyage calls**
(the 6/60 s test showed independent retries are unfair and can fail).

**Gemini Embedding** (100 RPM / 30K TPM / 1,000 RPD) is a **candidate to compare in M3**, not
only a fallback. Its rate limits are far more generous; the question is retrieval quality on
code. Caveats:
- Switching models means **re-embedding everything** (vectors from different models are not
  comparable). The M1 schema keeps embeddings separate from chunks, so no re-chunking is needed.
- Gemini's free tier may use prompts to train Google's models. Using it in the live app would
  need an **explicit decision** and a **privacy note in the README**.

### Capacity (what the free tiers add up to)
The whole app is a **~2–3 questions/min demo**:
- Voyage: 3 requests/min shared by every visitor (1 query = 1 request, unless cached).
- Groq plain RAG: ~3K tokens per question against 8K tokens/min → ~2.5 questions/min.
- Agent mode: ~1 question/min (tool turns resend the whole history).

Design consequences (M2 onward):
- **Bounded FIFO queue** in the backend for Voyage calls. If the estimated wait exceeds ~45 s,
  respond "busy, try again" instead of queueing.
- Show the **queue position** in the UI.
- **Pre-cache embeddings for the suggested questions** on featured repos (no Voyage call needed).
- **Queries have priority over ingestion** in the shared Voyage queue. Ingestion uses at most
  2 of the 3 slots per window, so a visitor's question never waits behind a whole repo.
- "Paste any repo" really means **tiny repos or featured repos**. Before starting an ingest, the
  UI shows the estimated ingest time (from `count`).

### Other M0 decisions
- **LLM:** `qwen/qwen3.8-27b` (tool tests 10/10 clean vs gpt-oss-120b 0/5 + 0/2). Model id in config.
- **Groq budget:** 8K input + 1K output tokens/min per model → plain RAG (no tool turn, ~3K
  tokens) is the default in M2; set `max_tokens` and ask for short answers; agent turns in M4
  must be lean.
- **Neon:** cold start ≈ 0.5 s, a non-issue. Reuse connections (pooling) in M2. Locally, pin IPv4.
- **M2 context format:** prefix each line of retrieved chunks with its absolute file line
  number, so citations don't depend on the model counting lines.

### Embedding candidates (free-tier limits as shown in dashboards)
| Option | RPM | TPM | RPD | Free pool | Notes |
|---|---|---|---|---|---|
| Voyage voyage-code-3, no card | 3 | 10K | – | 200M tokens | Code-specific. First 9K-token request 429'd 4× (no Retry-After) |
| Gemini Embedding 1 (AI Studio, free tier) | 100 | 30K | 1,000 | ongoing | General-purpose; free-tier data may be used by Google. Compare in M3 |

### Carry-overs (into M1 and later)
- **Pacer margin:** add a few seconds to the 60 s window. Voyage seems to count from request
  arrival or completion, not from our send time. → Planned in M1 (60 + 5 s).
- **Filtering:** exclude config-like `.py` files outside the package (e.g. `docs/conf.py`).
  → Planned in M1 (skip rules).
- **Gemini latency (148–224 s):** network ruled out. `curl -4` and `curl -6` to
  generativelanguage.googleapis.com both finish in ~0.4 s (connect ~0.07 s, TLS ~0.24 s).
  Next suspects: hidden SDK retries on 429/503, model "thinking", or free-tier queueing.
  Diagnose before the M3 eval: time a raw REST call, disable SDK retries, log status codes and
  rate-limit headers, and try a fixed model id with thinking off.
