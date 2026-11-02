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
Next.js chat UI + FastAPI endpoint; answers cite files and lines. Design decided in the M2
grilling (2026-11-02): see "M2 decision log" (Q1–Q19) and "M2 open assumptions and risks"
(R1–R12) below. Built as vertical slices: the first slice is a thin end-to-end path, later
slices widen it.

Pre-M2 fixes (done before the spike):
- `requirements-api.txt` (runtime only: no tree-sitter, no tokenizer, no voyageai SDK).
- The embedder calls Voyage over plain HTTP.
- The ETA includes per-request latency.
- `pytest` names the opt-in tests it didn't run and prints skip reasons.
- **Proven (2026-11-02):** in a fresh `.venv-api` with only `requirements-api.txt` +
  `pip install -e . --no-deps`, `tree_sitter`, `tokenizers` and `voyageai` are absent, and
  `python -m codeask.search` returned `Signer > derive_key` first (0.377; 0.378 via the SDK).

### [x] M2-0 Spike: hosting facts before design
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

### [x] Slice 0: spike follow-ups (R1, R2)
Redeploy the spike with `/ip`; call it with and without a forged `X-Forwarded-For`; call
`/slow?s=120` from the Vercel page.

**Done when:** "M2-0 results" records which header carries the real client IP and whether a
client can forge it (Q6b decided in the log), and whether a 120 s request survives Render's
proxy (if not, the busy threshold drops below the proven limit).

### [x] Slice 1 (M2a): thin vertical slice, local
**Done (2026-11-02):** sanity questions 5/5 with a valid citation in the expected file (model
comparison, strict); 3 permalinks checked by hand at `672971d…` (right file and lines);
the local page (`frontend/`, `POST /ask` on `codeask.api.app`) shows answers with citation
chips (prompt v2: e.g. 4–5 citations, all valid); 199 tests pass; comparison and decision in
the decision log (Q15a–e).

Retrieve → simple pack with absolute line numbers → Groq → parse `[path:start-end]` →
validate → permalinks at the stored SHA, for one featured repo (itsdangerous). Build order
(mentor review, 2026-11-02):
1. `backend/codeask/answer.py` (pure): numbering, packer (estimate `token_count` + ~3
   tokens/line, with a safety margin), prompt with **an unguessable per-request tag** in the
   `<file>` delimiters, citation parser, validator, rewrite to server-made `[n](cite:n)` links,
   permalinks. Tests in `test_answer.py`.
2. `backend/codeask/llm.py`: Groq over plain HTTP: timeouts, 429 with `Retry-After`, output
   limit and temperature set explicitly, raw rate-limit headers logged, `Authorization` never
   logged. Citations parsed only from the final answer text, never from reasoning text;
   `usage` is the truth for reasoning tokens (check Groq's per-model reasoning options).
3. CLI `python -m codeask.ask <repo> "<question>"`.
4. **Model comparison** (Q15), reusing the CLI pipeline. Don't over-tune the prompt on these
   questions.
5. `POST /ask` in `backend/codeask/api/app.py`.
6. Bare `frontend/` page (TypeScript): plain text, `cite:` links replaced by chips.

**`/ask` response:** one markdown string plus a citations list. The server rewrites each
marker into `[n](cite:n)`, strips links, images and `cite:` links the model wrote itself, and
builds permalinks only from validated block metadata (path segments URL-encoded). The frontend
renders `cite:` links as chips and drops every other link. `[path:a]` = one line; validation
stays strict (wholly inside one supplied block); unparseable markers stay plain text.

**Comparison rules, fixed before running it:** quality rubric per answer = correct / partial
/ wrong (judged by me). Decision rule: the higher valid-citation rate wins, provided its output
tokens per answer allow ≥ 2 questions/min (1,000 output tokens/min); ties go to qwen. The table
also records format compliance (share of markers that parse) and estimated vs actual prompt
tokens (`usage.prompt_tokens`), to calibrate the packer in slice 2.

**Done when:**
- for each of the 5 sanity questions, at least one valid citation overlaps the expected file,
  and I've checked 3 permalinks by hand at the pinned SHA;
- a question typed in the local browser page returns an answer with citation chips;
- pytest covers the parser and validator and passes: valid, wrong path, partly outside, fake
  marker from repo text, `<think>` content, reversed or zero ranges, a range spanning two
  blocks, leading `./` or `/` in paths, model-written `cite:` links, links and images;
- the qwen vs gpt-oss-120b table (questions above + one unanswerable: rubric, valid-citation
  rate, format compliance, output and reasoning tokens, latency, estimated vs actual prompt
  tokens, rate-limit headers) is in the decision log, with the default model chosen by the
  rule.

### [x] Slice 2 (M2a): backend complete
**Done (2026-11-03):**
- 271 offline tests pass via `scripts/check.ps1`: packer, grounding, API errors and limits,
  model check, and the offline Q5 regression.
- **Live Q5** (prompt v3, no cap, budget 2,000): the context is `signer.py:67-73`,
  `signer.py:129-213` (merged), `signer.py:227-242` and `serializer.py:190-241` (merged). The
  answer cites the `reversed(self.secret_keys)` loop (`signer.py:236-240`): **7/7 valid**, and
  it now explains verification instead of speculating (slice 1: partial).
- **End-to-end timing** (local, home network → Neon Ohio; Render numbers come in slice 6):

  | Step | Time |
  |---|---|
  | Voyage embed | 1.19 s |
  | Retrieve (search + `file_chunks`) | 1.91 s |
  | Groq | 1.51 s |
  | Total | 4.61 s |

  - Groq usage: `prompt_tokens` 2,588 vs estimate 1,982 (+606, inside the slice 1 band of
    +458..+652); 460 output tokens; `x-ratelimit-remaining-tokens` 8,000 → 4,812 after one
    question, so ~3.2K TPM per question ≈ 2.5 questions/min.
- **Local server** (`uvicorn --factory`): the startup model check logged "available: True";
  `/status` 2 ms; `/repos` 3.9 s on its first DB call from home (local connect, as in M2-0);
  the 3 featured repos are listed.
- `/boom`-style errors: JSON with CORS headers is proven by `test_api.py` (TestClient with an
  `Origin` header), not yet from a real browser page. That gets checked with the slice 3 page.

Full packer (Q11: budget on the numbered display, 12–15 candidates, per-file cap, merging,
class outlines), grounding rules (Q3, Q9: "couldn't ground", "possibly relevant", unverified
citations), prompt version recorded with every answer (`PROMPT_VERSION` stays in `answer.py`
next to the text it versions; delimited context (Q4) was done in slice 1), featured-repos
endpoint, `/status`, one DB connection per request (Q26, no app-side pool), JSON errors inside the CORS layer (M2-0 finding),
generic error text only, model check (Q15, Q24; no model fallback, Q15c), one worker (R10),
request-id logs without question text or IPs (Q16), Render's `HEAD /` answered.
Decisions from the plan review: Q20–Q26 below.

Build order (mentor review, 2026-11-03):
1. **Capture** (`eval/m2_candidates.py`, one Voyage request): top-15 candidates and the query
   vectors for the 8 comparison questions, so every later experiment and test is offline.
2. `store.file_chunks(slug, paths)`: metadata of every chunk in the candidate files (no
   content, no vectors), for gap checks and outlines; added to the capture file (DB only).
3. **Expected chunks** per question, written from the source before any packer variant is
   compared.
4. Packer (`answer.py`, pure) + the offline **variant comparison** on all 8 questions (Q20).
5. Grounding response (Q23).
6. `llm.available_models()`; `api/app.py` as `create_app(db, embedder, llm)`, run with
   `uvicorn --factory ... --workers 1 --no-access-log`: errors (Q22), model check (Q24),
   routes `GET/HEAD /`, `/status`, `/repos`, featured-only `/ask`.
7. `scripts/check.ps1`; regression test; one live end-to-end timing run.

**Done when:**
- pytest for the packer (budget never exceeded on the numbered display, cap counted before
  merging, merged ranges contiguous, no merge across a chunk or a gap over the max) and the
  grounding cases passes;
- **regression check:** for comparison Q5 (key rotation), the packed context includes
  `verify_signature` (slice 1's context lacked it, so both models speculated). If it isn't in
  the top 15, that is recorded as an M3 retrieval finding and the test checks the packer's
  behaviour on synthetic candidates instead (Q20);
- `/boom`-style errors reach the browser as JSON with CORS headers; busy responses carry
  `Retry-After`; a 422 never echoes or logs the question;
- slug normalization can't bypass the featured-only check (case, whitespace, `.git`, trailing
  slash); a question over 400 chars gets 422;
- one end-to-end timing run (Voyage, Groq, total) is recorded here;
- `scripts/check.ps1` runs all offline tests and I paste a green run.

**Capture results (2026-11-03, `eval/results/m2_candidates_2026-11-03.json`, top 15 + query
vectors):**
- Q5: `verify_signature` ranks **9th**; five signer.py chunks rank above it. `derive_key` is 6th.
- **Q6: `derive_key` is not in the top 15** (M3 retrieval finding, Q20).
- Rough simulation (cost = `token_count` + 3/line; no merging or outlines), required chunks
  missing per variant:

  | Variant | Budget 2,000 | Budget 2,500 |
  |---|---|---|
  | Hard cap 3 | Q5 verify_signature; Q6 verify_signature, derive_key; Q7 BadSignature | + Q5 derive_key |
  | Soft cap 3 | Q5 verify_signature; Q6 verify_signature, derive_key | Q5 both; Q6 derive_key; Q7 BadSignature |
  | Cap 4 | Q5 verify_signature; Q6 derive_key | + Q5 derive_key, Q7 BadSignature |
  | Cap 5, or no cap | Q6 derive_key only | + Q5 derive_key, Q7 BadSignature |

- **The Q5 rule (cap drops it → soft cap) doesn't rescue it:** the soft cap fills leftover
  budget with lower-ranked other-file chunks before the deferred ones get a turn.
- **2,500 is worse than 2,000:** greedy skip-and-continue packing isn't monotone in the budget.
  At 2,500 the Signer class header (`signer.py:76-127`, ~870 with its 37-line docstring) fits
  and pushes `derive_key` out. By Q20, the budget stays 2,000.
- **Real comparison** (`eval/m2_pack_compare.py`, the real `pack()` with merging and outlines;
  12 required / 9 supporting chunks):

  | Budget | Variant | Required packed | Missing required | Supporting | Mean estimate | Mean blocks |
  |---|---|---|---|---|---|---|
  | 2,000 | hard cap 3 | 8/12 | Q5 verify_signature; Q6 verify_signature, derive_key; Q7 BadSignature | 7/9 | 1,892 | 6.0 |
  | 2,000 | soft cap 3 | 8/12 | same as hard cap 3 | 7/9 | 1,939 | 6.1 |
  | 2,000 | cap 5 | 10/12 | Q6 derive_key; Q7 BadSignature | 8/9 | 1,953 | 5.5 |
  | 2,000 | **no cap** | **11/12** | Q6 derive_key (not retrieved) | 8/9 | 1,949 | 5.1 |
  | 2,500 | hard cap 3 | 7/12 | Q5 both; Q6 both; Q7 BadSignature | 8/9 | 2,270 | 6.8 |
  | 2,500 | soft cap 3 | 8/12 | Q5 both; Q6 derive_key; Q7 BadSignature | 8/9 | 2,418 | 6.8 |
  | 2,500 | cap 5 | 9/12 | Q5 derive_key; Q6 derive_key; Q7 BadSignature | 9/9 | 2,425 | 6.6 |
  | 2,500 | no cap | 9/12 | Q5 derive_key; Q6 derive_key; Q7 BadSignature | 9/9 | 2,416 | 6.2 |

  Decision: Q28.

### [ ] Slice 3 (M2b): frontend
Install frontend-design + `@playwright/test`. Repo picker (featured), question box (≤ 400
chars), answer via `react-markdown` without raw HTML or model links/images, citation links +
code panel (escaped text, line numbers, cited range highlighted, "view on GitHub"),
"unverified" citations, follow-up chips (Q8), "each question is answered on its own" note,
`aria-live` status (Q17).

**Done when:** locally I can pick a repo, ask, and click a citation that shows the right
lines in the panel; Playwright (mocked backend) passes: ask → answer → citation click,
unverified citation, injection render test (Q18).

### [ ] Slice 4 (M2c): queue and abuse controls
One FIFO over `/ask` paced by Groq headers + own output-token accounting (Q10), position and
estimated wait in `/status`, busy at ~60 s (or the slice 0 limit), per-IP limits in memory
with a salted hash (Q6, Q16), length limit, daily cap row in Postgres, daily outcome
aggregates, kill switch. Measure how often questions repeat; build in-memory live caches
only if they are common (R3).

**Done when:** pytest with a fake clock shows a burst beyond capacity gets queue positions or
"busy", never an unexplained error; per-IP and daily-cap refusals are deliberate and return
friendly messages (per-IP is a 429); the kill switch returns its friendly message; Playwright
passes the busy and cap flows.

### [ ] Slice 5 (M2d): pre-generated answers
Table + CLI to generate answers for my chosen questions through the live pipeline (Q13), a
review step, a local export script writing static JSON into `frontend/` (Q14), the
"pre-generated on <date> with <model>" label, SHA check.

**Done when:** every featured repo (dev DB for now) has 5–8 reviewed answers; clicking a
suggested question shows its answer instantly with zero Voyage/Groq calls; Playwright passes
"pre-generated answers with the backend down".

### [ ] Slice 6 (M2e): deploy
Prod Neon project + API role (Q7), `.env.prod` with an explicit flag and host confirmation,
gitleaks scan → CodeAsk public → pinned release commit (Q12), ingest the featured repos and
generate their answers in prod, new Render + Vercel services with final names, CORS to the
Vercel origin, cold-start UX (Q14), privacy footer (Q16, R11), delete the spike services and
rotate the keys set there, freeze `spike/m2/` (Q19).

**Done when:**
- the `db` test proves the API role cannot write content tables or delete;
- the deployed API exposes no ingestion route (checked against its route list);
- 3 cold starts after ≥ 15 min idle are recorded from the deployed page (time until
  "waking up" turns ready, and time to the first answer), and the UI never shows a raw error
  during them;
- the manual smoke checklist passes on the public URLs (ask, citation, unverified display,
  pre-generated, busy, cap via kill switch);
- Render's Billing page shows usage within the free limits a week after launch;
- **before going public**, the Render card is removed (services keep running), or the
  decision log has the "card on file" exception with mitigations (build spend limit $0,
  auto-deploy off, low-limit card), and CLAUDE.md's stack row is updated (R7).

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
- DB connections: one per request through Neon's pooled endpoint, no app-side pool in M2
  (Q26).

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
- **Bandwidth:** the citation view gets the cited lines plus a little context, never whole
  files (100 KB files x 1,000 clicks/day ≈ 3 GB/month, too close to a 5 GB cap). Answers alone
  stay ≈ 1.5 GB/month even at the 1,000/day Groq cap.

### M2-0 results
**Outcome (2026-11-02):** Render works for the backend (card on file, see below), Vercel for
the frontend. Northflank was untestable (signups disabled); Koyeb was not needed.

**Local run (2026-11-02, home network → Neon Ohio, not representative of Render):**
`/search` returned `Signer > derive_key` first; Neon connect ~1.6 s warm, 7.7 s on the first
call (Neon's compute was probably suspended). CORS from `http://localhost:3000` worked.
**Finding:** an unhandled exception (`/boom`) reaches the browser as "Failed to fetch", not as
a 500. Starlette builds that 500 outside the CORS middleware, so it has no CORS header. M2a must
return errors as JSON from exception handlers inside the CORS layer, so the UI can tell
"server error" from "server asleep / unreachable".

| Item | Result |
|---|---|
| Render: signup without a card? | **No (2026-11-02):** GitHub signup worked, but clicking Deploy on a Free web service asked for a card. Third-party "no card" reports are out of date. **Decision:** Northflank signups were disabled, so I added a card on Render. Only usage beyond the free limits (e.g. bandwidth) can bill; keep the instance type Free, add no paid services, and keep responses small (see the bandwidth note in M2 inputs) |
| Render: free-tier terms checked (date, 2026 plan change, bandwidth) | Checked 2026-11-02 on the Billing page (see bandwidth row). Dashboard banner: spin-down "can delay requests by 50 seconds or more" |
| Render: region / Python version | Ohio; Python **3.13.0** via `PYTHON_VERSION` (confirmed in the build log). First deploy 54.9 s. Auto-deploy **off** (saves build minutes). URL: `https://codeask-spike.onrender.com` |
| Render: cold start after 15+ min idle (browser, time to first byte) | **24.3 s** (20.6 min idle, `/db` from the Vercel page; Neon's share 0.66 s, so Render's wake ≈ 23 s); `/health` right after: 0.31 s. Earlier accidental run after ~35 min idle: ~18–23 s. Render's banner says "50 seconds or more"; we measured about half, twice. UX idea for the grilling: the page calls `/health` on load (a real visitor, so not a keep-alive ping) and shows "waking up the server" after a few seconds |
| Render: warm request time | `/health` 0.38 s first byte from my PC (mostly the round trip to Ohio). `/search` 1.6 s end to end: connect 29 ms + **Voyage embed 1,223 ms** + pgvector search 76 ms |
| Render: memory (RSS) at start / after a real search | **54 MB / 78 MB** of 512 MB. Plenty of headroom for a connection pool and an in-memory cache |
| Render: 60 s request from the browser | **Works:** `/slow?s=60` returned 200 after 60.5 s (Chrome, localhost:3000 → Render). A second identical GET sent 8 s later took 80.8 s: Chrome's cache lock holds an identical GET up to 20 s. So `/ask` is a **POST**. `/boom` again shows "Failed to fetch" (no CORS header on the 500) |
| Render → Neon: connect / query time (warm Neon) | fresh connect **20 ms**, `SELECT 1` 1 ms, chunk count 3 ms, vector search 76 ms (local: ~1.6 s / 825 ms) |
| Render → Neon: first connect with Neon suspended (both wake on one request?) | Neon suspends after ~5 min idle. First connects after idle: **658 ms** and **3,210 ms** (warm: 20 ms). So the first question after a quiet spell can pay Render's wake **plus** Neon's; measured together in the cold-start test |
| Render: bandwidth allowance / what happens when over | **Billing page (2026-11-02):** per workspace per month: 750 free instance-hours, **5 GB bandwidth** counting HTTP responses **and service-initiated traffic** (our calls to Voyage/Neon/Groq), **500 pipeline (build) minutes**, 25 services, 2 custom domains. "You will be charged for usage beyond your included limits." Auto-deploy on every push would spend build minutes: keep it off or filter paths |
| CORS locked to the Vercel origin (other origin refused?) | **Works:** `Origin: http://localhost:3000` gets `access-control-allow-origin`, `https://evil.example` gets no CORS header. CORS only stops other *websites* reading replies; curl and scripts still get through, so abuse control is M2c's job (per-IP limits, daily cap), not CORS. Vercel origin still to add |
| Render: logs free of secrets | Build and startup logs: **no secrets**. Render sets `WEB_CONCURRENCY=1` (one worker): the in-process Voyage limiter needs exactly one, so pin it explicitly in M2. Access logs show client IP and full URL, so questions must go in a POST body, not the query string. Render probes `HEAD /` and `GET /` (404 in the spike), so the real API should answer `/`. `/boom` traceback: file paths and code lines only, no values. Log search (24 h) for `npg_`, `postgresql://`, `VOYAGE`, `DATABASE_URL`, `pa-`: **no hits**. M2a: send the browser a generic error, never exception text (psycopg errors name host and user) |
| Vercel: signup without a card? Hobby terms | **No card asked (2026-11-02).** GitHub signup, Hobby plan. GitHub app limited to CodeAsk. Root dir `spike/m2/web`, first deploy 21 s |
| Vercel page → Render from the browser | **Works** from `https://codeask-pi.vercel.app`: `/health` 0.66 s, `/db` 4.5 s (Neon waking), `/search` 1.8 s (embed 1.37 s), same top result. Gotcha: Render env changes only apply with a deploy ("Save only" does nothing to the running service) |
| CORS with the Vercel origin | `ALLOWED_ORIGINS=http://localhost:3000,https://codeask-pi.vercel.app`: both get the header, `evil.example` doesn't |
| Long requests (slice 0, 2026-11-02) | `/slow?s=120` → 200 after 121.1 s; `/slow?s=95` → 200 after 95.4 s (curl; a proxy cut-off would hit the browser the same way). No Cloudflare 100 s cut-off on Render |
| Client IP (slice 0, 2026-11-02) | Render sits behind Cloudflare (a `162.159.x.x` hop in `X-Forwarded-For`). With a forged `X-Forwarded-For: 1.2.3.4`: the leftmost entry **and uvicorn's `request.client.host` both became 1.2.3.4** (forgeable). `True-Client-IP` and `CF-Connecting-IP` kept the real IP; a forged `True-Client-IP` was overwritten; a forged `CF-Connecting-IP` made Cloudflare reject the request (error 1000). Render doesn't document the Cloudflare layer |
| Northflank: card asked at signup? sleeps? free limits | **Blocked (2026-11-02):** "sign up is disabled right now" (GitHub sign-in errored first). Card question untested |

### M2 decision log (grilling, 2026-11-02)
| # | Decision | Why | Rejected alternative |
|---|---|---|---|
| Q1 | **Scope:** the public deployment offers featured repos only, with pre-generated answers for suggested questions; no ingestion endpoint on the internet. "Paste a URL" stays local (CLI now, a local UI later); README and CLAUDE.md say so | The 3 Voyage requests/min are shared with live questions, and an ingest of even a tiny repo holds up to 2 of them for minutes. Public cloning on a 512 MB instance adds attack surface and size-limit work that doesn't teach RAG | Public "paste any URL" in M2 (the original pitch and M0 outcome) |
| Q1b | **Later, restricted:** a hosted "try your own tiny repo" only after M2c's queue and abuse controls are proven and M3 is done: size cap, one ingest at a time, ETA confirmation, queries take priority | Keeps the original idea without letting it shape M2 | Never; or now |
| Q2 | **Response mode:** `/ask` (POST) returns one whole answer. A cheap `/status` (awake, queue length, estimated wait) is polled by the UI while waiting; the first poll on page load also wakes a sleeping server. Revisit streaming only if measured generation (qwen reasoning tokens included) reaches 5–10 s | The long waits are cold start (~24 s) and queue, which streaming can't shorten; citations are validated on the complete answer before anything is shown; 60 s requests survive Render's proxy (M2-0) | SSE token streaming; submit-then-poll |
| Q3 | **Grounding:** answer only from the supplied context. If it's missing, say so and list the closest retrieved files as "possibly relevant"; partial answers allowed with the missing part marked. No general-knowledge fallback. An answer with no valid citation is not shown as an answer. No distance threshold. Unanswerable questions go into the M3 eval set | Guessing hides retrieval failures that M3 must measure; cosine distances aren't calibrated across questions or repos | General-knowledge fallback; a distance cut-off |
| Q4 | **Prompt injection:** (a) system prompt + clearly delimited context blocks, (b) output checks: only validated citations, no model-supplied links or HTML. (c) filtering suspicious chunk text is skipped; revisit at M4 (tools) or if "own repo" returns | Featured repos are chosen by me; (b) also defeats fake citation markers in repo text | Chunk filtering now |
| Q5 | **Citation click:** GitHub permalink at the stored commit SHA (`blob/<sha>/<path>#L<a>-L<b>`) first, then an in-app panel built from stored chunk content (cited lines lie inside the supplied context, so no `files` table), with a "view on GitHub" link. Code rendered as escaped text | Permalinks never drift; the panel needs no new table and sends only cited ranges (bandwidth) | A `files` table; panel only; permalink only |
| Q6 | **Abuse limits:** per IP: 1 question in flight, modest hourly and daily limits (config). Question ≤ ~400 chars. Global daily cap ≈ 500–600 Groq calls (1,000/day minus a reserve for tests and pre-generation), tuned from use. At the cap: "live quota used up for today", pre-generated answers keep working. Kill-switch env var. Storage per Q16: per-IP counters in memory, the daily cap in Postgres | Capacity is ~2–3 questions/min; per-IP limits stop casual abuse only, the global cap is the backstop | Per-IP counters persisted |
| Q6b | **Client IP header (slice 0):** read the client IP **only from `CF-Connecting-IP`**. If it's missing (Render's Cloudflare layer is undocumented and could change), the request goes into one shared "unknown" bucket with a strict limit, and a warning is logged | Measured: a client can forge `X-Forwarded-For`, and uvicorn's `request.client.host` follows it; `CF-Connecting-IP` can't be forged (Cloudflare rejects it) | `request.client.host`; leftmost `X-Forwarded-For`; `True-Client-IP` (not forgeable either, but kept only as a cross-check) |
| Q7 | **Data topology:** a **separate Neon project** for the demo. The API's DB role has SELECT on content tables and INSERT/UPDATE only on its own `usage` table. Prod URL lives in a gitignored `.env.prod`, loaded only by an explicit flag; ingest against prod prints the DB host and asks for confirmation. Featured repos are re-ingested into prod (minutes); prod has its own embedding store | Free compute (100 CU-h/month) and storage (0.5–1 GB, sources conflict) are per project, shared by its branches, so dev and M3 runs can't suspend the demo | Same DB; a branch of the dev project; a fully read-only role (breaks the DB-backed daily cap) |
| Q8 | **Single-turn:** each question answered on its own; the UI says so. After an answer, follow-up chips built from the cited chunks' breadcrumbs with fixed templates (no LLM, no history) | History costs Groq tokens per minute and needs query rewriting for retrieval | Follow-ups with history (M4 topic) |
| Q9 | **Citation contract:** inline `[path:start-end]`, parsed by the server. Valid only if the path matches a supplied block and the range lies wholly inside its supplied lines (**blocks after merging**; partly outside = unverified, no clamping). Valid ones become links; invalid ones are shown as "unverified" and counted (M3 metric). Zero valid citations means "couldn't ground this in the code" plus the "possibly relevant" files. No regeneration in M2 | Inline keeps each claim next to its source; markdown in JSON strings is fragile; regeneration costs a second Groq call | JSON output; silently dropping invalid citations; regenerate once |
| Q10 | **Queue:** one FIFO over the whole `/ask` path, paced by Groq's headers (`*-tokens` = TPM, `*-requests` = RPD per Groq docs) **plus our own output-token accounting** from each answer's `usage` (qwen's 1,000 output tokens/min is not in the headers). Busy at ~60 s estimated wait (120 s requests proven in slice 0); the UI shows position and estimated wait. Optional small exact-match answer cache (repo, commit, normalized question, prompt version, model), labelled "answered earlier", only if it stays small | A cache hit skips Voyage but never Groq, so Groq is the real bottleneck | Voyage-only queue; spinner without position |
| Q11 | **Context packing:** budget ~2–2.5K tokens (config), counted on the numbered display. Retrieve ~12–15 candidates, pack greedily by rank, per-file cap 2–3 chunks (**counted before merging**), merge adjacent same-file chunks, present grouped by file in line order. Class outlines only when a header chunk is retrieved, size-capped. M3 tunes the values | ~2–2.5K context keeps ~3 questions/min under 8K TPM; the cap fights M0's near-duplicates | Fixed k=5; ~3K budget |
| Q12 | **Featured repos:** itsdangerous, requests, express, and CodeAsk itself, **pinned to a release commit** and refreshed only at milestones. Before featuring CodeAsk: make it public after a full-history secret scan (gitleaks). TableTalk and flask optional later | Python + JS, small to medium, plus a self-referential demo | Featuring CodeAsk at `main` (answers go stale every commit) |
| Q13 | **Pre-generated answers:** ~5–8 questions per repo, chosen by me, answered by the live pipeline, each answer and its citations reviewed by me. Stored with commit SHA, prompt version, model id and date; labelled "pre-generated on <date> with <model>"; shown only if the SHA matches the repo's current one (re-ingest ⇒ regenerate). Generation counts against the daily cap, serving doesn't | Instant, free answers that are honestly labelled | LLM-written questions; serving stale answers |
| Q14 | **Cold-start UX:** the page polls `/status` on load (retry every 2–3 s for ~60–90 s, since a waking server can fail without CORS headers), shows "server waking up", never locks the input, and sends a submitted question once the server is up. Pre-generated answers ship as **static JSON written by a local export script and committed** (Vercel never gets DB credentials) | Visitors can read and type during the ~24 s wake | Locking the input; a Vercel build-time DB export |
| Q15 | **Model:** compare qwen3.8-27b and gpt-oss-120b in slice 1 on a fixed set of 5–8 questions (sanity set + a few more, one unanswerable): answer quality, citation validity, output and reasoning tokens, latency, rate-limit headers; check whether reasoning can be lowered or hidden. qwen stays default until the data says otherwise; result recorded here. Startup check that the configured model exists; a fallback model id in config | M0 only tested tool calls; M2 needs plain cited answers. Groq's free catalogue changes | Assuming qwen; a second model as overflow (later idea) |
| Q15a | **Result (slice 1, 2026-11-02): qwen3.8-27b is the default** (`reasoning_effort: none`). By the rule fixed before the run (higher valid-citation rate wins if output tokens allow ≥ 2 questions/min; ties to qwen): strict validity qwen 45/46 (98%) vs gpt-oss 0/1; qwen averages 334 output tokens (~3 questions/min). The decision stands on the strict numbers alone. Table and grades: "M2 model comparison" below | gpt-oss cited in its own formats (`【…】`, U+2011, short paths), so its citations couldn't be verified even where its content was right | gpt-oss-120b as default |
| Q15b | **Lenient citation notation** (added **after** seeing the results): structural variants only as observed (`【…】`, several citations in one bracket, a bare range keeping the previous path), each validated on its own. **Every Unicode dash (category Pd) and U+2212 is normalized to "-"**, only inside the bracket content being parsed, never in displayed text. Paths stay exact. Strict and lenient rates are both reported | Accepts the observed notation without loosening validation; dashes are typography, brackets and lists are structure | Accepting short paths; unobserved bracket styles |
| Q15c | **No model fallback.** Rule fixed before re-scoring: gpt-oss is the fallback only if its lenient validity is ≥ ~80% of qwen's with no new failure modes. Result: 21/31 (68%) = 69% of qwen's 98%, plus a new failure mode (all 10 unverified citations are short paths). When qwen fails, the demo serves pre-generated answers plus a notice; `GROQ_FALLBACK_MODEL = None` | Under "zero valid citations ⇒ couldn't ground", a fallback whose citations don't verify is useless | gpt-oss-120b as fallback |
| Q15d | **A valid citation proves location, not truth.** Validation shows the cited lines were in the supplied context, not that they support the claim (qwen's Q3 `=` claim cites real lines yet misleads). Claims are graded by hand (rubric + "grounded?"); later (M3) a judge model can check support | Keeps "valid-citation rate" from being read as an accuracy score | Treating validity as correctness |
| Q15e | **Prompt v2** (`PROMPT_VERSION`, recorded with every answer): cite per group of related claims, at most ~5 citations, copy the full path from the file tag | qwen cited up to 10 times per answer; gpt-oss shortened paths | Re-tuning the prompt on the comparison questions |
| Q16 | **Visitor data:** per-IP limits use in-memory counters keyed by a hash of the IP with a random per-process salt, never persisted. The global daily cap is one Postgres row per day; Groq's 429s stay the ground truth. **No question text stored.** Only aggregate outcomes per day (answered, ungrounded, busy, unverified-citation rate, tokens, latency). App logs: request id, status, durations, outcome; never question text or IPs. Footer + README: questions go to third-party APIs (Groq, Voyage), nothing stored beyond counters (wording after checking their data terms) | Visitor questions have no known correct files, so they're useless as M3 eval data; storing less means less to protect | Storing raw IPs or questions |
| Q17 | **Frontend stack:** Next.js + TypeScript, Tailwind only (frontend-design skill for the look), plain React state, one types file for the API. `react-markdown` without raw HTML; model-supplied links and images blocked (only the server creates citation links). Code panel: escaped plain text with line numbers and the cited range highlighted; no syntax highlighting in M2. Status messages in an `aria-live` region. No secrets in `NEXT_PUBLIC_` variables. Tests with the official `@playwright/test`; keep only one of webapp-testing / playwright skill | Few moving parts; safe rendering by construction | shadcn/ui; Shiki; a state library |
| Q18 | **Tests:** backend pytest with fakes for parser, validator, packer, queue (fake clock) and limits, plus one `db` test proving the API role cannot write content tables or delete. Frontend Playwright against a mocked backend: ask → answer → citation click shows the right lines; invalid citation shown as "unverified"; cold start with a delayed `/status` and the question sent once up; busy and cap messages; pre-generated answers with the backend down; injection render (`<script>`, `<img onerror>`, markdown link and image in an answer: nothing executes or renders). Real end to end = a manual smoke checklist in slice 6. `scripts/check.ps1` runs all offline tests; I run it and paste the output | Pure functions with fakes need no network; the mocked backend makes UI states reproducible | Live API calls in tests |
| Q19 | **Layout and spike services:** `backend/codeask/api/` and `frontend/` with separate deploy roots. New Render and Vercel services with the final names; the spike services are deleted after the results are recorded, and any key set there is rotated. `spike/m2/` stays as a frozen record with a one-line README, checked for secrets, and added to CLAUDE.md's frozen-files line | Clean names and settings for the real app; the spike stays as evidence | Reusing the spike services |

**Slice 2 plan review (2026-11-03, mentor):**

| # | Decision | Why | Rejected alternative |
|---|---|---|---|
| Q20 | **Packer variants compared offline, not tuned to Q5:** on all 8 comparison questions, from saved candidates and expected chunks written beforehand: hard cap 3 vs **soft cap** (capped-out candidates deferred, filling only leftover budget in rank order), budget 2,000 vs 2,500. The simplest variant that includes all expected chunks wins; 2,500 only if it shows a recall gain. Q5 rule: not in the top 15 → M3 retrieval finding, synthetic regression test; dropped by the cap → soft cap; dropped by the budget → consider 2,500 | Slice 1's Q5 context had signer.py 3 times by rank 5, so a hard cap of 3 could exclude `verify_signature` regardless of budget; one question is not a basis for tuning | Choosing cap/budget from Q5 alone |
| Q21 | **Merge rule:** two same-file blocks merge when no chunk of that file lies in the gap (by the coverage invariant, the gap is blank lines) **and** the gap is ≤ ~5 lines | Chunks exclude blank separator lines (`175-180` and `182-213` have line 181 between), so `end + 1 == start` would almost never fire | Strict adjacency; any blank gap |
| Q22 | **Errors:** a catch-all middleware registered first (innermost), CORS after (outermost); JSON `{error, message, request_id}`, never exception text. Groq 429 → 503 "busy" + `Retry-After`; upstream 5xx → 502; timeouts → 504; per-IP limits (slice 4) → 429; the 422 handler never echoes or logs pydantic's `input` (it holds the question) | Starlette's `exception_handler(Exception)` runs outside CORS (the M2-0 `/boom` finding) | `app.exception_handler(Exception)` |
| Q23 | **Grounding response:** zero valid citations → `grounded: false`, no answer text sent (kept in `raw_answer` for eval); `possibly_relevant` = top 3 distinct files by candidate rank (dropped candidates included), labelled as a retrieval suggestion | Q3: an answer without a valid citation is not shown as an answer | Showing the ungrounded text; packed blocks only |
| Q24 | **Model check:** at startup and again with a TTL (≥ 10 min); degraded (no crash) when Groq's list lacks the model or Groq reports it missing; `/ask` then returns 503 "live answers unavailable" | A crash would restart-loop on Render; Preview models can vanish mid-run (R13) | Startup-only check; crashing |
| Q25 | **Class outlines: names only in M2**, in a separate uncitable `<outline-TAG>` element; prompt v3 adds "cite only lines shown in file blocks". Line ranges return in M4 with `read_file` | Ranges in an outline invite citations of lines the model never saw (unverified) | Names + ranges (M2 inputs); signature lines as numbered blocks |
| Q26 | **DB connections:** one connection per request via a small context manager; no `psycopg_pool` in M2. Revisit if the measured connect time per request is consistently above ~100 ms | Neon's pooled endpoint (PgBouncer) is already a pool; Render → Neon connect measured ~20 ms (M2-0); no new dependency; no open question about whether an idle open connection blocks Neon's scale to zero | An app-side `psycopg_pool` (the original "pooling" item) |
| Q27 | **Expected chunks** (`eval/m2_expected.json`, ranges from `672971d…`): drafted by Claude from the source before the slice 2 candidates were printed; **confirmed by me after I had seen the printed candidates**, with edits: Q7 adds `exc.py:22-33` BadSignature as required (the slice 1 grading treated omitting `payload`/message as partial, so the set must include where `payload` is defined); Q1 adds the Signer class header (`default_key_derivation`) as supporting. A range counts as packed when every **non-blank** line of it lies inside the packed blocks after merging. Committed before the packer experiment; later changes are amendments with a reason | The variant rule (Q20) needs a target fixed before the variants are compared | Choosing expected chunks after seeing packing results |
| Q28 | **Packer default: no per-file cap, budget 2,000 (provisional).** Overrides Q11's cap. `PER_FILE_CAP` stays a parameter (default `None`) for the M3 ablation. **Evidence is one small repo** (itsdangerous, 8 questions, 12 required chunks): in slice 5, re-run `eval/m2_pack_compare.py` on requests and express using the pre-registered expected chunks of their suggested questions; if the result flips, revisit the cap (per repo or in M3). Q6 `derive_key` not being in the top 15 is an M3 retrieval finding. **Why 2,500 packs fewer than 2,000:** greedy skip-and-continue packing is not monotone in the budget. In Q5 at 2,000 the Signer class header (`signer.py:76-127`, ~870 with its 37-line docstring) doesn't fit and is skipped, leaving room for `derive_key` and `verify_signature`; at 2,500 it fits and `derive_key` no longer does. Only a stop-at-first-misfit greedy is monotone, and it would lose both at 2,000. So there is no "more budget never removes a chunk" test; a test pins the skip behaviour instead | Only no cap at 2,000 packs every retrieved required chunk (11/12); it's also the simplest variant (Q20 rule). M1 chunks don't overlap, so the near-duplicates the cap targeted (M0) are gone; on a small repo the answer genuinely sits in one file and a cap pushes weaker other-file chunks in | Hard cap 3 (fails the Q5 regression check); soft cap 3 (same); cap 5; budget 2,500 |

### M2 model comparison (slice 1, 2026-11-02)
pallets/itsdangerous, 8 questions (`eval/m2_models.json`, Q8 unanswerable), one Voyage request,
models alternating 35 s apart. Raw data and answers: `eval/results/m2_models_2026-11-02*`;
re-scored offline with `eval/m2_rescore.py`.

| | qwen3.8-27b (reasoning off) | gpt-oss-120b (reasoning low) |
|---|---|---|
| Valid / cited, strict | **45/46 (98%)** | 0/1 |
| Valid / cited, lenient (Q15b) | 53/54 (98%) | 21/31 (68%) |
| Parsed / attempted brackets, strict → lenient | 46/50 → 50/50 | 1/31 → 31/31 |
| Expected file hit (7 answerable), strict / lenient | 7/7 / 7/7 | 0/7 / 5/7 |
| Unverified causes (lenient) | 1 path typo (`url_safepy`) | 10 short paths |
| Output tokens per answer, mean (range) | 334 (191–462) | 283 (112–423) |
| Reasoning tokens (`usage.completion_tokens_details`) | none reported | 16–114 |
| LLM latency | 1.2–1.7 s | 1.1–2.3 s |
| `prompt_tokens` minus packer estimate (system prompt + question + tokenizer gap) | +458 to +652 (estimate 875–1,984) | +83 to +375 |
| Rate-limit headers | 1,000 RPD, **8,000 TPM** | 1,000 RPD, 8,000 TPM |
| Quality rubric (correct / partial / wrong, by me) | **6 / 2 / 0** (partial: Q3, Q5) | **6 / 2 / 0** (partial: Q5, Q7) |
| Grounded? (vs the supplied context) | **8 yes** | 7 yes, **Q5 no** |

Three separate judgements per answer: **correct** (vs the source, graded by me), **grounded**
(vs the context the model was given: yes / partly = a minor unsupported detail / no = the
central claim is unsupported), **citations valid** (server check, strict / lenient). The
contexts were reconstructed from the clone at `672971d…` into
`eval/results/m2_models_2026-11-02_context.json`; from now on `ask()` stores each answer's
context.

| Q | qwen: correct · grounded · valid (strict / lenient) | gpt-oss: correct · grounded · valid (strict / lenient) | Notes |
|---|---|---|---|
| 1 key derivation | correct · yes · 10/10 / 10/10 | correct · yes · 0/0 / 6/6 | gpt-oss used `【…】` |
| 2 max_age | correct · yes · 4/4 / 4/4 | correct · yes · 0/0 / 3/3 | |
| 3 compression | partial · **yes** · 9/10 / 9/10 | correct · yes · 0/0 / 7/7 | qwen's "alphabet includes `=`" matches the supplied `_base64_alphabet` (encoding.py:41-46); the padding strip (line 25) wasn't in the context, so nothing there contradicts it: grounded yes, yet partial vs the source. 1 unverified = path typo `url_safepy` |
| 4 base64 padding | correct · yes · 3/3 / 3/3 | correct · yes · 0/1 / 0/3 | gpt-oss's 3 short paths point inside the supplied lines |
| 5 key rotation | partial · **yes** · 4/4 / 8/8 | partial · **no** · 0/0 / 0/7 | `verify_signature` wasn't in the context. qwen flagged the gap and labelled its inference; gpt-oss stated the loop as fact. gpt-oss's 7 short paths point inside the supplied lines |
| 6 wrong salt | correct · yes · 5/5 / 7/7 | correct · yes · 0/0 / 3/3 | |
| 7 exception | correct · yes · 5/5 / 7/7 | partial · yes · 0/0 / 2/2 | gpt-oss omits `payload` and the message |
| 8 unanswerable | correct · yes · 5/5 / 5/5 | correct · yes · 0/0 / 0/0 | both say it's not in the files |

"Grounded" for the answers without a note: checked by Claude against the reconstructed
context (every valid citation lies in it; uncited claims spot-checked).

**Decision rule applied (2026-11-02):** quality ties (6/2/0 each). Valid-citation rate:
strict 98% vs 0%, lenient 98% vs 68%: **qwen wins under both**; both models stay under 500
output tokens per answer. Default: qwen3.8-27b (Q15a). The comparison used prompt v1; v2
(cite per group of claims, ≤ ~5 citations, full path from the file tag) came afterwards and
is not re-tuned on these questions.

### Not in M2 (scope guard)
- Hosted ingestion of user-supplied URLs (see Q1b).
- Token streaming (SSE), conversation history, regeneration of bad answers, chunk-text
  filtering against injection, a second overflow model, syntax highlighting.

### M2 open assumptions and risks
| # | Assumption / risk | How it's settled |
|---|---|---|
| R1 | Render's client-IP header may be spoofable (community reports conflict with Render staff) | **Settled in slice 0:** use `CF-Connecting-IP` (Q6b). Remaining risk: Render drops Cloudflare; then the "unknown" bucket applies |
| R2 | `/ask` stays open for queue wait + processing (~65–70 s at a 60 s busy threshold); only 60 s was proven | **Settled in slice 0:** 120 s requests return 200, so the ~60 s busy threshold stands |
| R3 | **Caches vs "no question text stored" (Q16):** a persisted cache keyed by the normalized question would store visitor questions | **Resolved (2026-11-02):** live caches in memory only; persisted entries only for my own suggested questions. No live answer or embedding cache is built in M2 unless slice 4 measurements show repeated questions are common |
| R4 | qwen's reasoning tokens may count against 1,000 output tokens/min and lengthen answers | Slice 1 model comparison |
| R5 | Groq's free catalogue changes; the configured model can disappear | Startup model check (Q15); no model fallback (Q15c), so pre-generated answers + a notice |
| R13 | **qwen3.8-27b is a Groq "Preview" model** ("should not be used in production"); it may change or disappear. Same risk for M4's tool calls | Not a reason to change the default. Mitigations: pre-generated answers as graceful degradation; model id in config + startup check; when choosing any future fallback, check Groq's production vs preview lists; the re-runnable comparison (`eval/m2_compare.py` + `m2_rescore.py`): switch default, re-run, regenerate pre-generated answers (each records model id and date); README says "tested with qwen3.8-27b (Groq Preview) as of Nov 2026"; M4 agent mode stays an eval/replay feature |
| R6 | Neon prod storage is 0.5 or 1 GB (sources conflict); compute 100 CU-h/month per project; Neon wake adds 0.7–3.2 s to a cold request | Check the prod project's dashboard in slice 6 |
| R7 | Card on file at Render (docs: optional; in practice asked at my first deploy). With a card, overage **bills** instead of suspending: bandwidth beyond 5 GB at $0.15/GB with **no spend cap** (HTTP responses, service-initiated traffic, DB responses leaving Render); build minutes beyond 500 (cappable: Workspace Settings → Build Pipeline → spend limit); custom domains beyond 2 at $0.25/month. Email alerts near and over limits (not configurable). 750 instance-hours are shared by all services in the workspace | Try removing the card; if it must stay: decision-log exception, build spend limit $0, auto-deploy off, low-limit virtual card, delete spike services. **If a card isn't acceptable: Northflank free Sandbox is the fallback** (retry signup; untested because signups were disabled on 2026-11-02), then Koyeb |
| R8 | One Voyage key for local ingestion and the live app; the limiter is in-process, so a local prod ingest can collide with live queries | Ingest into prod only when the demo is idle, or with reserved slots |
| R9 | Per-IP limits reset on restart/sleep and are bypassed by IP rotation | Accepted; the global daily cap and Groq's own limits are the backstop |
| R10 | The in-process limiter and queue need exactly one worker; the queue must stay shorter than the thread pool (AnyIO default 40) | Pin `WEB_CONCURRENCY=1` / `--workers 1`; a config assert on the queue length |
| R11 | Groq and Voyage data terms decide the privacy footer wording | Read their terms before slice 6 |
| R12 | Render's free tier is "not for production" and its terms change (the card requirement surprised us) | Re-check terms at deploy; Koyeb/Northflank as fallbacks |

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
- **M2 note (R13):** the tool-calling model (qwen3.8-27b) is a Groq Preview model and may
  change or disappear, so agent mode stays an **eval/replay feature**.

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

**Outcome:** keep Voyage, no card. Design = pre-indexed featured repos + file filtering +
query-embedding cache (small on-demand repos: **later, restricted**, see the M2 decision log), **plus a FIFO queue in the backend for Voyage calls**
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
- **Neon:** cold start ≈ 0.5 s, a non-issue. Reuse connections in M2 (superseded: one connection per request, Q26). Locally, pin IPv4.
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
