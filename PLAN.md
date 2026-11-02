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

## [x] M1 Ingestion
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

### M1 "Done when" check (2026-11-02)
| # | Item | Evidence |
|---|---|---|
| 1 | Ingest command; chunk fields | Steps 6 + 9: itsdangerous, requests, express ingested; schema columns NOT NULL |
| 2 | Re-run = 0 requests, no duplicates; body edit = 1 new embedding | Final re-ingests of itsdangerous and requests on v4: 0 new texts, 0 requests; `db` tests `test_rerun_…`, `test_body_edit_…` |
| 3 | Manual interruption | Step 6: first ingest resumed (51 cached → 19 embedded); re-ingest left the old index searchable |
| 4 | Tests | Final code: 159 unit tests, 6 `db` tests (real Neon, fake embedder), 1 `slow` test (real tokenizer), all green |
| 5 | `search` + sanity | itsdangerous sanity hit@5 = 5/5, MRR@10 = 1.00 (v3; v4 leaves Python identical) |
| 6 | Summaries recorded | Step 9 tables (per-category chunks/tokens, distribution, windowed units, skips, tokens/min). "Line exceeds token cap" skips: **0** for all three repos |

Final state:
- All three repos are stored under CHUNKER_VERSION 4.
- `m0_chunks` dropped; `spike/m0.py` is frozen (its docstring says so).

### M1 task list (build order)
1. ✅ **Skeleton:** root `pyproject.toml` (editable install, package in `backend/codeask/`, pytest
   config), pinned `requirements.txt`, `requirements-dev.txt` (pytest). `pytest` runs from the
   repo root.
2. ✅ **tree-sitter smoke test:** parse one Python, JS, TS and TSX file and print the node-type
   names; record them here (see "Step 2 results" below). If tree-sitter-typescript 0.23.2 won't
   load with tree-sitter 0.26, pin the newest tree-sitter that works.
3. ✅ **File filters** + tests (plus a rule not in the grilling: symlinks are never followed) (skip rules, categories, per-file reasons).
4. ✅ **Python chunker** + tests + the real-corpus sweep over the 5 cloned repos.
   Sweep (2026-11-01, fake ~4 chars/token counter, max 800, tests + docs included): invariants
   hold on all 574 files; no chunk over 759.
   | Repo | Chunks | Median | p95 | Max | < 60 tokens |
   |---|---|---|---|---|---|
   | itsdangerous | 115 | 124 | 477 | 737 | 10 |
   | requests | 492 | 156 | 502 | 754 | 55 |
   | flask | 1,169 | 171 | 489 | 743 | 99 |
   | TableTalk | 1,548 | 190 | 498 | 759 | 108 |
   | express (all windows until step 7) | 387 | 469 | 483 | 491 | 10 |

   Changes made while building:
   - Parts of a split function are packed greedily up to the target. The sibling rule (merge
     only below the min) would cut a function of 125-token statements into 125-token parts.
   - The class header holds only the attributes **before** the first member, because a chunk
     must be one contiguous line range. Later attributes merge with their neighbours.
   - A header over the cap (long docstring) is windowed, and part 1 keeps the method outline.
     Found by the real-tokenizer test on itsdangerous `Signer` (37-line docstring).
5. ✅ **`count` command.** Compare with the M0 table: expect ~15–20% fewer tokens, because the
   10-line overlap is gone. Result (real tokenizer, `spike/m1_count_output.txt`):
   | Repo | M0 all | M1 all | Change | M1 source + README (default) | Requests | ETA |
   |---|---|---|---|---|---|---|
   | itsdangerous | 20,384 | 19,831 | −3% | 11,922 | 5 | 1.1 min |
   | requests | 116,076 | 103,244 | −11% | 58,623 | 21 | 6.5 min |
   | flask | 287,037 | 258,954 | −10% | 90,940 | 32 | 10.8 min |
   | express | 176,465 | 153,567 | −13% | 33,477 | 12 | 3.2 min |
   | TableTalk | 453,866 | 411,341 | −9% | 182,001 | 65 | 22.8 min |

   The drop was smaller than expected, for two reasons:
   - **Overlap only cost ~17% in files longer than one window.** A file under 60 lines had
     no overlap (itsdangerous: −3%). Express, still all windows, shows the pure overlap saving:
     −13%.
   - **Syntax chunks add context back:** more chunks, each with its own `File:`/`Scope:` lines,
     plus context lines on split pieces and outlines on class headers.
   - The skip rules fired as intended: `docs/conf.py`, empty `__init__.py` files, the 100 KB+
     `test_requests.py`, TableTalk's `contract.gen.ts` and 4 `fixtures/` files.
   - **M3:** `requests` source = 58.6K tokens ≈ 6.5 min per variant, right at the ≤ 60K rule.
   - ETA basis: 3K-token requests, 3 per 65 s ≈ 8.3K tokens/min. To be verified in step 6.
6. ✅ **Vertical slice on itsdangerous (Python only):** schema + store (`repos`, `chunks`,
   `embeddings`; drop `m0_chunks`) → embedder + shared limiter → `ingest` CLI (clone with
   `--ref`, ETA + confirm, embed with a commit per batch, transactional swap, summary) + `gc` →
   `search`. Run it; re-run (0 requests); interruption test; sanity questions; measure
   tokens/min.

   Built per the step 6 review:
   - Injected embedder; `ingest_directory()` separate from the clone.
   - 6 `db` integration tests on a throwaway Neon schema with a fake embedder.
   - Git hardening: strict URL/ref, env vars, timeout.
   - The limiter stamps at completion; gc keeps orphans < 24 h.
   - Schema-qualified SQL, because the pooler drops `SET search_path`.
   - `m0_chunks` kept until the final M1 cleanup.

   Results (2026-11-02):
   - **Interruption on a first ingest:** Ctrl+C after 3/5 batches; the re-run found
     51 cached and embedded only 19.
   - **Interruption on a re-ingest** (psf/requests `--tests`, Ctrl+C during batch 4's slot
     wait): `search` still returned only `src/` paths (the old index stayed live), and `gc`
     deleted 0 (young orphans kept as resume cache).
   - **Re-run = 0 requests.** Switching variants back (`--tests` → default) = 0 requests.
   - **Sanity** (itsdangerous, 5 M0 questions in one request): hit@5 = 5/5, MRR@10 = 1.00.
     The top hits are now the right *functions* (`Signer > derive_key`,
     `TimestampSigner > unsign`, `base64_decode`), not just the right files. For M3: the
     key-rotation question matched `Signer > secret_key` (its docstring mentions rotation)
     rather than `verify_signature`, which does it. File-level scoring hides that.
   - **Throughput (psf/requests source, 21 full requests): 7,845 tokens/min, 0 × 429**
     (58,623 tokens in 448 s). The limiter predicted Voyage's window exactly (requests at
     4 / 71 / 148 / 230 … s).
   - **The ETA runs ~15% short** (6.5 min predicted, 7.5 actual): each window lasts 65 s plus
     that request's latency (2–12 s), because slots are stamped at completion. Matters for
     M2's "busy past ~45 s" estimate.
   - **The cross-process gap showed up for real:** a re-run started seconds after an
     interrupted run got 1 × 429 (the new process's limiter didn't know about the old
     process's 3 requests). The retry handled it; a shared limiter is on the M2 list.
7. ✅ **JS/TS chunker** (named units from the step 2 node names, export wrappers, const arrow
   functions, Express callbacks) + tests + corpus sweep.

   Built per the step 7 review (CHUNKER_VERSION 2):
   - Per-language specs. **Python output proven unchanged** by a snapshot of all 2,999
     chunks in 249 `.py` files (`spike/chunk_snapshot.py`): identical.
   - **Named units:** callbacks only when the first argument is a string/template literal
     (`app.get("/users/:id")`, `describe("Router")`); function assignments by their left side
     (`app.handle`); `function_signature` overloads; namespaces as containers.
   - **Attachment:** closing-bracket-only glue attaches to the previous unit; TS sibling
     decorators attach like comments.
   - **Window fallbacks report a reason.** The hand-written TS sample (decorators, abstract
     class, generics, generators) found that a decorator on an *abstract* method doesn't
     parse: TypeScript doesn't allow it. The sample was fixed, not the chunker.

   Sweep + count (2026-11-02):
   | | express before (windows) | express AST | TableTalk before | TableTalk AST |
   |---|---|---|---|---|
   | Source tokens | 30,307 | 33,628 (+11%) | 179,657 | 184,013 (+2%) |
   | Source chunks | 88 | 337 | 674 | 959 |
   | Median (source + README) | 421 | 82 | 216 | 136 |
   | Under 60 tokens | 4 | 114 (33%) | 55 | 130 (13%) |
   | Requests / ETA (default) | 12 / 3.2 min | 13 / 4.3 min | 65 / 22.8 min | 66 / 22.8 min |

   - express: 142/145 files AST (the other 3 are markdown); 0 parse-error fallbacks anywhere.
   - **Window-fallback reasons, whole corpus:** shared-line composite (K&R) **0**; IIFE **2**
     (TableTalk, not worth supporting); oversized anonymous unit 5 (data-like statements);
     class header over cap 5 (long Python docstrings, outline kept on part 1).
   - **M3 ablation candidate:** express is very fine-grained (a third of its chunks are under
     60 tokens). Small named functions alternate with anonymous statements (`require`,
     `exports.x = …`), and like-with-like merging stops at every switch, so the File/Scope
     header dominates tiny embeddings. Compare "like with like" vs "merge any small
     neighbour".
8. ✅ **README splitter** + tests; **fixed-window fallback** polish (other languages, parse
   errors) + tests.

   Built per the step 8 review (CHUNKER_VERSION 3; decisions in the log above):
   - `markdown.py` line scanner; per-line "embed view" for docs (noise stripped, over-cap
     lines truncated); no chunk with an empty embeddable body.
   - **Code output proven unchanged:** snapshot of 4,036 chunks in 445 .py/.js/.ts files,
     identical (windows compared in naive mode).
   - **A bug found by the tests:** the Markdown fence scanner treated a reST `~~~~` underline as
     an unclosed fence, hiding every later heading. Fences are now Markdown-only.

   Results (2026-11-02, sweep with fake counter; count with real tokenizer):
   | Docs | Before (windows) | After (sections) |
   |---|---|---|
   | flask (79 .rst) | 257 chunks, 107,239 tokens | 408 chunks (346 section, 58 part, 8 merged), 110,590 tokens (+3%) |
   | itsdangerous | 12 chunks, 3,854 tokens | 30 chunks, 4,053 tokens |
   | express (.md) | windows | 15 sections + 1 intro |

   - express is now 145/145 files AST. The remaining windowed files have no grammar (e.g.
     itsdangerous `.devcontainer/on-create-command.sh`).
   - Doc lines truncated in embed_text: **0** across the corpus (a safety net, not yet needed).
   - Oversized paragraphs windowed: 8 (TableTalk 7, requests 1).
9. ✅ **Real runs:** express (source) and a re-run of itsdangerous; record the summaries.

   Results (2026-11-02, CHUNKER_VERSION 3, default categories = source + README):
   | Repo @ commit | Chunks (source / doc) | Tokens | Median / p95 / max | < 60 | Windowed units | Requests | Time |
   |---|---|---|---|---|---|---|---|
   | expressjs/express @ 1c6f1b0fe400 | 353 (337 / 16) | 36,587 | 82 / 315 / 623 | 117 | oversized paragraph 1 | 13 new, 0 × 429 | 293 s (ETA 4.3 min → 4.9 actual) |
   | pallets/itsdangerous @ 672971d66a2e | 72 (69 / 3) | 11,877 | 122 / 505 / 714 | 5 | class header over cap 1 | 1 (5 new, 67 cached) | 4 s |
   | psf/requests @ 3c7baaa05ab4 | 292 (288 / 4) | 58,456 | 154 / 520 / 756 | 33 | class header 1, oversized anonymous 1 | 1 (8 new, 284 cached) | 6 s |

   - **Throughput:** express 7,481 tokens/min (partial last batch); requests 7,845. 0 × 429
     in either run.
   - **Re-ingest new texts** = README chunks (now sections) **plus windowed units whose
     boundaries moved** with `window_prefer_blank_lines` (e.g. `Signer`'s docstring header).
     Every function/class/merged chunk came from cache.
   - **Sanity** (itsdangerous, v3 chunks): hit@5 = 5/5, MRR@10 = 1.00, same top results.
   - **JS spot check** ("How does the router match a request path to a route?"):
     - #1 was `app.route`'s **JSDoc block**, as its own chunk; #2 was the function.
       Express puts a blank line between every `/** */` and its function, so the
       comment-attachment rule (no blank line) splits docs from code across the repo. This
       explains much of the 33% of chunks under 60 tokens.
     - Express 5 moved path matching into the separate `router` package, so that code isn't
       in this repo. M3 questions must be answerable from the repo itself.

   **JSDoc fix (CHUNKER_VERSION 4, decision log above), results:**
   - Snapshot: Python **identical** (2,475 chunks); JS/TS changed in 154 files, as intended.
   - express (source + README):
     | | v3 | v4 |
     |---|---|---|
     | Chunks | 353 | 287 (−19%) |
     | Tokens | 36,587 | 35,854 (−2%) |
     | Median | 82 | 96 |
     | Under 60 tokens | 117 (33%) | 66 (23%) |
   - **Re-ingest: 71 new embeddings, 216 cached, 6 requests instead of 13.**
   - **Spot check:** `app.route` is now one chunk (lines 246–258: JSDoc + function), still #1.
     For M3: the combined chunk scored 0.431, versus 0.391 for the JSDoc alone in v3. Pure
     prose sits closer to an English question, so code dilutes the match slightly. It is still
     first and now holds the code; the `jsdoc_attach_across_blank` ablation will show whether
     this costs rank on harder questions.
10. ✅ **Record** the results here and commit. "Done when" checked item by item (table above);
    the slow test had been silently skipping since the M0 clone was deleted. Its path now
    follows the ingest clone, and it passes.

### Step 2 results: tree-sitter node types (spike/ts_smoke.py, 2026-11-01)
All four grammars load in tree-sitter 0.26.0 (Python and JS grammars ABI 15; TypeScript and TSX
ABI 14). Root nodes: `module` (Python), `program` (JS/TS/TSX).

| Unit | Python | JS | TS / TSX (in addition to JS) |
|---|---|---|---|
| Function | `function_definition` | `function_declaration` | |
| Decorated (wrapper holding its decorators) | `decorated_definition` | | Decorators sit inside `export_statement`, before the class |
| Class | `class_definition` > `block` | `class_declaration` > `class_body` | `abstract_class_declaration` |
| Class members | `function_definition`, `decorated_definition`, `expression_statement` (attributes, docstring) | `method_definition` | `public_field_definition`, `abstract_method_signature` |
| Const function | | `lexical_declaration` > `variable_declarator` > `arrow_function` / `function_expression` | Same |
| Export wrapper (unwrap to name the unit) | | `export_statement` > declaration | Same |
| Type-level | | | `interface_declaration`, `type_alias_declaration`, `enum_declaration`, `expression_statement` > `internal_module` (namespace) |
| Express callback path | | `expression_statement` > `call_expression` > `arguments` > `arrow_function` > `statement_block` | Same |
| Docstring | `expression_statement` holding a single `string`, first in module/class/function body | | |
| Comment | `comment` | `comment` | `comment` |
| Anonymous (merge candidates) | `import_statement`, `import_from_statement`, `expression_statement` (assignments, calls), `if_statement` | `lexical_declaration` (non-function), `expression_statement` (`module.exports = …`, calls) | `import_statement` |

Findings that affect the chunker:
- **A broken file looks valid at the unit level.** `def broken(:` parsed as a normal
  `function_definition` with no visible ERROR node among the named children; only
  `root.has_error` was True. This confirms the whole-file fallback rule (per-unit detection
  would have missed it).
- **Units share lines in real code.** `MAX = 10  # constant` gives `expression_statement [5-5]`
  and `comment [5-5]`. The "units sharing a line must merge" rule is needed, not theoretical.
- **Namespaces hide inside a generic node** (`expression_statement` > `internal_module`), so
  named-unit detection must look one level into `expression_statement`.
- Not in the samples, to cover in tests: Python `async def`, JS `var` (`variable_declaration`),
  `export default class`, `export { a, b }` lists, multiple declarators in one `const`.

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
| **JSDoc (step 9 → CHUNKER_VERSION 4):** a `/** */` comment attaches to the next **named** unit across **one** blank line; blocks with `@file`, `@fileoverview`, `@module`, `@license`, `@copyright`, `@typedef`, `@callback` or `@namespace` never attach; `//` and Python `#` keep the no-blank-line rule. Flag `jsdoc_attach_across_blank` (M3 ablates it) | **Observed failure:** express puts a blank line between every JSDoc block and its function, so docs and code were separate chunks across the repo ("router matching" returned `app.route`'s JSDoc #1 and the function #2, separately) | Leaving it as an M3 ablation (the baseline would start with docs and code split on every JS repo); attaching any comment across blanks (section headers would attach) |
| Class over the max: header chunk (own lines + **capped** method-signature outline in `embed_text`, counted toward the cap) + method chunks | "What can X do?" matches the header | Header without an outline |
| Function over the max: split at top-level statements; recurse into compound statements and into call arguments → callback bodies (with the call's first line as context); then line windows; **never oversize**. Each piece carries the signature | The hard cap stays strict; Express callbacks get real chunks | Oversized chunks |
| A line over the token cap: skip the file (measured with the real tokenizer; the character rule is a cheap pre-filter); count reported. If it drops meaningful files, revisit by truncating that line in `embed_text` only | "No chunk exceeds the max" is true by construction | Cutting lines by characters (breaks citations and coverage) |
| **Line over the cap, reconciled (step 8):** code files are skipped as data-like (as above); **Markdown/reST lines are truncated in `embed_text` only**, with displayed content and line ranges intact. Round 2 exempted markdown from the line-length rule, but round 3 made the skip universal; docs legitimately have long unwrapped lines | A long paragraph shouldn't hide a whole README | Skipping doc files with one long line |
| Doc noise (step 8): badges/images, HTML-tag-only lines, reference-link definitions and YAML front matter are stripped from `embed_text` only. A piece with no embeddable text attaches to its neighbour | No URL noise in embeddings; citations still match the file | Dropping the lines (breaks coverage) |
| Doc sections (step 8): split at H1/H2 (ATX, setext, reST underlines; reST level = order of first appearance); an over-cap section splits at its next heading level, then by paragraph (fences whole), then line windows | Headings are the document's own boundaries; sentences can't be split inside a line range | A markdown grammar; sentence splitting |
| Windows (step 8): prefer ending at a blank line in the final quarter (`window_prefer_blank_lines`, M3 runs both); whole-file windows labelled `<module> (part i)` without a total | Breaks between functions; appending to a file doesn't relabel (re-embed) earlier windows | Fixed cut points; `part i/n` everywhere |
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
Next.js chat UI + FastAPI endpoint; answers cite files and lines. Built in six parts. The
design of M2a–M2e is decided in a grilling session **after** the M2-0 spike results are in.

Pre-M2 fixes (done before the spike):
- `requirements-api.txt` (runtime only: no tree-sitter, no tokenizer, no voyageai SDK).
- The embedder calls Voyage over plain HTTP.
- The ETA includes per-request latency.
- `pytest` names the opt-in tests it didn't run and prints skip reasons.
- **Proven (2026-11-02):** in a fresh `.venv-api` with only `requirements-api.txt` +
  `pip install -e . --no-deps`, `tree_sitter`, `tokenizers` and `voyageai` are absent, and
  `python -m codeask.search` returned `Signer > derive_key` first (0.377; 0.378 via the SDK).

### [ ] M2-0 Spike: hosting facts before design
Render (free web service), running a throwaway `spike/m2/` FastAPI app on the API
requirements:
- card-free signup? Current free-tier terms. Reported (third-party, 2026-11-02): 512 MB RAM,
  0.1 vCPU, spins down after 15 min idle, wake ~1 min, 750 instance-hours/month per workspace
  (all free services suspended when used up), ephemeral disk. **Bandwidth is unclear:** one
  source says 5 GB/month, then $0.15/GB (Apr 2026). Confirm on render.com/docs/free and
  render.com/pricing, and check whether going over can bill without a card
- Ohio region; pinned Python version
- **cold start after 15+ min idle** (time to the first byte, measured from the browser)
- **memory** with the API requirements loaded (RSS after a real search), against 512 MB
- a **60 s request** from the browser: does Render's proxy keep it open?
- **CORS** locked to the Vercel origin (a request from another origin is refused)
- **Neon connect and query time from Render** (same region)
- **logs never show secrets** (deploy log, startup, an error path)

Vercel (Hobby): a Next.js hello page that calls the Render API **from the browser**.

Second candidate: **Northflank** free Sandbox (reported: always on, no sleep). Its pricing page
says "No card needed"; its billing docs reportedly require a payment method before creating
resources. Verify with a real signup and record whether a card was asked for. **Koyeb** only if
Render and Northflank both fail (its free-tier reports conflict on card and free compute).

**Done when:** every item above has a measured or confirmed value recorded in "M2-0 results"
below, and anything that contradicts the plan is flagged.

### [ ] M2a Backend core
FastAPI: `/ask` (retrieve → pack context → Groq → validated citations), repo/featured
endpoints, connection pooling.

**Done when:** a local `/ask` on an ingested repo returns an answer whose every citation is
validated server-side against stored chunks, with tests for the packer and the validator.

### [ ] M2b Frontend
Next.js chat UI: repo picker (featured), question box, answer with clickable citations, safe
markdown rendering.

**Done when:** locally, I can pick a repo, ask in the browser, and click a citation that shows
the right file and lines.

### [ ] M2c Queue and abuse controls
Bounded FIFO Voyage queue, "busy" responses, queue position, a global daily cap, per-IP rate
limits.

**Done when:** a burst test (more queries than slots) gets a queue position or "busy, try
again" for every request, with no 429 reaching the user and no error, and the daily cap shows
a friendly message.

### [ ] M2d Pre-generated answers
Suggested questions per featured repo, answered offline, stored with citations, labelled
"pre-generated".

**Done when:** clicking a suggested question answers instantly with zero Voyage/Groq calls, and
the UI marks it as pre-generated.

### [ ] M2e Deploy
Render (API) + Vercel (UI), featured repos only, no ingestion endpoint on the internet.

**Done when:** the public URLs work end to end, cold start is recorded here, and the deployed
API exposes no ingestion route.

### M2 inputs (requirements collected in M0 and the M1 grilling)
**Context building**
- Number every line of the retrieved chunks with its **absolute file line number** (not 1..n per
  chunk), so citations don't depend on the model counting lines.
- **Token-budget context packing:** fill the context up to ~3K tokens instead of a fixed k=5
  (Groq: 8K tokens/min per model).
- **Class header chunks:** when one is retrieved, build the method outline from its child chunk
  rows (names and line ranges) and include it in the context, so the model sees what matched.
- **Near-duplicates:** M0's top 5 were often all from one file. Consider a per-file cap.
  Decide in M2.
- **The context packer merges adjacent retrieved chunks from the same file** into one block
  (with absolute line numbers), e.g. a function retrieved together with the chunk just above
  it. Fewer seams, fewer repeated File/Scope headers, and citations stay one contiguous range.

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

**From the M1 step 6 review**
- **Embedding dimension:** the table is `vector(1024)`. Gemini Embedding (or a smaller Voyage
  `output_dimension`) uses other sizes. Decide before M3: one table per dimension, or
  `vector` without a fixed size (no index possible) or a reduced common size.
- **A `files` table** (repo, path, content) for `read_file` and the UI. Render's disk is
  ephemeral, so the clone can't be the source of truth after a restart.
- **Per-repo advisory lock** (`pg_advisory_xact_lock`), so two ingests of the same repo can't
  interleave.
- **Repo-size limits for user-supplied URLs:** a token cap from `count`, refused before any
  embedding, plus clone size/time limits.

**From the M1 review (before M2)**
- **The limiter is synchronous** (`threading` + `time.sleep`). Use plain `def` FastAPI
  endpoints, which run in a thread pool, never `async def` that would block the event loop.
  Keep the max queue length **below the thread-pool size**, so waiting requests can't starve
  the pool. `Limiter.acquire()` currently has **no timeout**: M2c must add one (or refuse
  up front when the estimated wait is over ~45 s), so no request thread waits a full window.
- **The packer budgets for the numbered display:** `chunks.token_count` counts `embed_text`,
  but the LLM sees lines with absolute line numbers (~3 extra tokens per line). Budget from
  the displayed text.
- **Groq output budget:** qwen allows ~1,000 **output** tokens/min, so long answers cut capacity
  below 2 questions/min. Keep answers to ~350 tokens; measure output tokens per answer, and
  whether reasoning tokens count toward the limit.
- **Global daily cap:** Groq allows 1,000 requests/day. Count them and answer with a friendly
  "daily limit reached, try again tomorrow" before Groq does.
- **Pre-generated answers for suggested questions:** generated offline, stored with their
  citations, labelled "pre-generated" in the UI (M2d).
- **Server-side citation validation:** every `path:start-end` in an answer must match a stored
  chunk of that repo; invalid citations are dropped or flagged, never shown as links.
- **Safe markdown rendering:** no raw HTML from the model in the UI.
- **Public deployment = featured repos only.** No ingestion endpoint on the internet;
  ingestion stays a local CLI job.
- **Consider a separate Neon branch or database for the public demo,** so local experiments
  can't break it.
- **The browser calls the backend directly,** with CORS locked to my origin. Long queue waits
  don't go through Vercel functions (their timeouts and invocation limits).
- **No keep-alive pings** (Render treats them as abuse). Handle cold starts in the UI.

### M2-0 results
_Fill in during the spike._

**Local run (2026-11-02, home network → Neon Ohio, not representative of Render):**
`/search` returned `Signer > derive_key` first; Neon connect ~1.6 s warm, 7.7 s on the first
call (Neon's compute was probably suspended). CORS from `http://localhost:3000` worked.
**Finding:** an unhandled exception (`/boom`) reaches the browser as "Failed to fetch", not as
a 500. Starlette builds that 500 outside the CORS middleware, so it has no CORS header. M2a must
return errors as JSON from exception handlers inside the CORS layer, so the UI can tell
"server error" from "server asleep / unreachable".

| Item | Result |
|---|---|
| Render: signup without a card? | |
| Render: free-tier terms checked (date, 2026 plan change, bandwidth) | |
| Render: region / Python version | |
| Render: cold start after 15+ min idle (browser, time to first byte) | |
| Render: warm request time | |
| Render: memory (RSS) at start / after a real search | |
| Render: 60 s request from the browser | |
| Render → Neon: connect / query time (warm Neon) | |
| Render → Neon: first connect with Neon suspended (both wake on one request?) | |
| Render: bandwidth allowance / what happens when over | |
| CORS locked to the Vercel origin (other origin refused?) | |
| Render: logs free of secrets | |
| Vercel: signup without a card? Hobby terms | |
| Vercel page → Render from the browser | |
| Northflank: card asked at signup? sleeps? free limits | |

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
- **Chunking ablations planned from M1:**
  - merge policy: like-with-like (current) vs merge-any-small-neighbour vs a higher
    `min_tokens` (express had 33% of chunks under 60 tokens);
  - the windows control (`chunker = "windows"`), naive and with `window_prefer_blank_lines`;
  - `embed_include_path` / `embed_include_scope` on and off;
  - tests / docs included or not.
  Report retrieval metrics overall **and by chunk kind** (function, class_header, merged,
  part, section, window, ...), so a strategy that wins overall but hurts one kind is visible.
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
**Measured in M1 step 6: 7,845 tokens/min** (psf/requests, 21 full requests, 0 × 429), so the
"~8.5K/min" column below is ~8% optimistic.

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
