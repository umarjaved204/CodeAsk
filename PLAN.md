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

### [x] Slice 3 (M2b): frontend
**Done (2026-11-11).** Every Done-when item below is met:
- design: direction A and tokens approved (Q31-Q33);
- tests: 98 browser tests against the mocked API, 60 logic tests, and axe with no violations;
- review: three screenshot rounds approved (Q41), and both review passes (step 5);
- the manual real-backend check passed: CORS JSON error with the request id in the page.

Carried forward:
- slice 4 confirms the provisional state 5 shape (Q40) and decides the `/ask` fetch timeout;
- slice 5 brings suggested questions, the example question placeholder and the shareable `?repo=`;
- slice 6 brings the strict CSP for the theme script, ESLint 10 and TypeScript 7, and the real-phone check.

Install frontend-design + `@playwright/test`. Repo picker (featured), question box (≤ 400
chars), answer via `react-markdown` without raw HTML or model links/images, citation links +
code panel (escaped text, line numbers, cited range highlighted, "view on GitHub"),
"unverified" citations, follow-up chips (Q8), "each question is answered on its own" note,
`aria-live` status (Q17).

**Design first (addendum, 2026-11-03):** an excellent, distinctive design, not a generic
AI-looking one. In this order, before any component code:
1. **Design brief:** one /grill-me round (≤ 6 neutral questions): audience (recruiters,
   interviewers, developers), tone, 3 reference sites I admire, light/dark default, density,
   any brand/wordmark. The brief is written here. Product requirements come from the decision
   log:
   - citations as numbered chips;
   - a code panel with line numbers and the cited range highlighted;
   - unverified citations visibly different;
   - a calm ungrounded state;
   - an honest "about this demo" note (featured repos, rate-limited, pre-generated answers
     labelled).
2. **Direction:** with frontend-design, 2–3 distinct visual directions as short written specs,
   each with a static HTML mock of the main screen, rendered to PNGs with Playwright (I run
   it), read and presented. I pick; the decision and the rejected options are recorded. If
   frontend-design alone gives generic results, say so; ui-ux-pro-max is then considered (its
   bundled Python script reviewed first).
3. **Design tokens:**
   - colour (light and dark), type scale, spacing, radii and shadows, as Tailwind theme / CSS
     variables;
   - text contrast checked against WCAG AA with a small script;
   - fonts via `next/font`, self-hosted (no runtime requests to font services);
   - code in a monospace font.
4. **State inventory:** empty, loading, waking, queued, busy, daily cap, error, ungrounded,
   unverified citations, very long answer, long code lines, many citations, mobile. Every
   state is designed, not only the happy path. Waking, queued, busy and daily cap are backend
   features of slices 4 and 6: here they exist as mocks, with a provisional response shape
   that slice 4 confirms.
5. **Visual review loop:**
   - A Playwright script, using the same mocks as the tests, screenshots every state at
     390×844, 768×1024 and 1440×900, light and dark, into a gitignored
     `frontend/design-review/`.
   - I run it; Claude reads the PNGs, critiques them against the brief (hierarchy, spacing,
     contrast, overflow, truncation) and fixes.
   - 2–3 rounds, then I look and decide.
6. **Accessibility in tests:**
   - `@axe-core/playwright` on every state;
   - a keyboard-only flow (ask, open a citation, close the panel);
   - visible focus;
   - `prefers-reduced-motion` respected;
   - `aria-live` status messages;
   - meaning never carried by colour alone (verified and unverified chips also differ by icon
     and text).
7. **Review passes:** web-design-guidelines and vercel-react-best-practices are used ONLY as
   review passes, at the end of slice 3 and again in slice 6. They list findings; I decide
   which to fix; only high-impact items relevant to this small app are applied.
   web-design-guidelines fetches its rules at run time (from
   `raw.githubusercontent.com/vercel-labs/web-interface-guidelines`).

Constraints: Tailwind only, no component library, no extra UI dependencies without asking; the
Q17 rules stand (`react-markdown` without raw HTML, no model links or images). Open design
question for the build plan: the code panel needs the cited lines, but `/ask` returns no
context today (`public_view()` withholds it). Settled in the brief round as Q30.

**Design brief (grilling, 2026-11-03):**
- **Audience, in order:** recruiters, then interviewers/engineers, then developers.
  - The first screen shows value with zero interaction: a pre-generated example answer with
    visible citation chips, labelled pre-generated (date, model, commit), with the ask box
    right below and the repo picker.
  - Interviewers verify by clicking a citation. Developers go straight to the picker and the
    box.
- **Character:** precise, calm, trustworthy; quietly editorial. The answer is set like a
  well-typeset article, with citations acting as footnotes.
  - **Avoid:** the startup landing page (gradient hero, glass effects), terminal cosplay (neon
    on black), emoji-heavy UI. Also frontend-design's listed defaults: cream + serif +
    terracotta, ALL-CAPS eyebrow labels, identical soft-shadow cards, `·` meta strings, `→` on
    buttons, monospace for labels.
- **References:** none given (the question came back as the unfilled template three times).
  Work from the brief alone; I name references if a direction misses.
- **Theme:** follows the system setting, with a toggle. Both themes are designed equally,
  and the theme is applied before first paint (no flash of the wrong theme).
- **Layout, desktop:** side by side.
  - The answer sits in a reading column under ~80 characters per line.
  - The code panel is on the right, with the **first valid** citation pre-opened, so the
    evidence is visible without a click.
  - Long code lines scroll horizontally.
- **Layout, mobile:**
  - The panel is a bottom sheet, closed by default, with a hint: "Tap a citation to see the
    code".
  - Chips open the sheet. Nothing opens automatically.
  - A partial-height peek gets revisited only if the screenshots feel empty.
- **The ask box is visible without scrolling** at 1440×900 and 390×844 (or sticky), checked
  by screenshots.
- **The repo picker defaults to itsdangerous.** The other repos show their suggested questions
  once slice 5 lands.
- **A "How it works" link** in the header or footer, to the repo README (a slot for the M3
  results later). No new page.
- **Brand:** a text wordmark in the chosen typeface, plus a tiny glyph echoing the citation
  brackets (`[ ]`) that doubles as the favicon. It stands on its own.
- **Example answer:**
  - The itsdangerous key-rotation question, from the live pipeline.
  - Graded by me with the three-column rubric (correct, grounded, citations valid) before it
    becomes the fixture.
  - Saved as a static fixture with date, model, prompt version, commit SHA and the cited
    lines (Q30), and labelled pre-generated.
  - Slice 5 replaces it with the reviewed set.
  - Hand-built mocks cover the state inventory: ungrounded, unverified citations, very long
    answer, many chips, long code lines.
- **Non-negotiables:** WCAG AA contrast, a keyboard-only path, reduced motion respected,
  `aria-live` status messages.
- **Product requirements** (decision log):
  - numbered citation chips;
  - a code panel with line numbers and the cited range highlighted;
  - unverified citations visibly different, by icon and text and not by colour alone;
  - a calm ungrounded state;
  - an honest "about this demo" note: featured repos only, rate-limited, pre-generated
    answers labelled.

**State inventory (step 4, approved 2026-11-03 with the mentor's changes):**

| # | State | Trigger | What it shows |
|---|---|---|---|
| 1 | First screen | Page load | The example answer with the sentence label "Example answer, generated <date> with <model> on commit <sha7>". Desktop: first valid citation open. Mobile: sheet closed + "Tap a citation to see the code" |
| 2 | Empty | A repo with no example yet (requests, express until slice 5) | "Ask a question about the code in <repo>. Answers cite the lines they use." Space for suggested questions (slice 5) |
| 3 | Loading | Question sent | The question becomes the heading; the button reads "Asking…" and is disabled. Status: "Answering. This usually takes a few seconds." with an indeterminate pulse that stops under reduced motion. Panel: "The cited code appears here." **After ~12 s:** "Still working. This demo is rate-limited, so it can take up to a minute." |
| 4 | Waking | `/status` unreachable on load (any non-JSON response counts as waking) | 0–35 s: "Waking up the server. This takes about 30 seconds after a quiet spell." 35–90 s: "Still starting. This is taking longer than usual." Then state 9. The input stays usable; a question submitted meanwhile is sent once, automatically, when the server is up ("Your question will be sent when the server is ready.") |
| 5 | Queued (mocked; shape confirmed in slice 4) | Queue position > 0 | "2nd in line, about 40 seconds." |
| 6 | Busy | 503 `busy` | "The demo is at capacity. This demo runs on free tiers, so only a few questions fit per minute." A manual "Try again" with a countdown from `Retry-After`, announced at the start and at zero. No auto-retry |
| 7 | Daily cap (mocked) | Cap reached | "Today's live questions are used up. The limit resets daily; the example answers still work." |
| 8 | Model unavailable | 503 `model_unavailable` | "Live answers are unavailable right now. The example answers still work." |
| 9 | Error | 500/502/504, or no response after the waking window | Server error: "The server couldn't answer (request <id>). Try again." No response: `navigator.onLine` false → "You're offline. Check your connection and try again."; otherwise "Can't reach the server." with a retry |
| 10 | Ungrounded | `grounded: false` | Heading "No cited answer for this question". "The answer couldn't be tied to lines in <repo>, so it isn't shown. These files came closest:" then ≤ 3 files as GitHub permalinks (new tab, `rel="noopener noreferrer"`, external-link icon), then "Naming a function or file usually helps." Empty panel |
| 11 | Unverified citation | `valid: false` | Chip in the `unverified` colour with a "?" icon and dashed underline; accessible name "Citation 3, unverified". The chip is a button that does NOT open the panel: it toggles an inline note with the claimed path and range (escaped text) |
| 12 | Very long answer | ~600 words | The column scrolls under the sticky ask box, with a fade edge above it; the panel stays put |
| 13 | Long code lines | Lines wider than the panel | Horizontal scroll inside the panel; line numbers stay visible (sticky left) |
| 14 | Many citations | ~12 chips | Chips wrap in the text; the panel's citation list scrolls |
| 15 | Mobile sheet open | Chip tapped | Bottom sheet up to ~80% height with a title and a "Close" button; Esc closes; a keyboard user can never reach the page behind the sheet (after its last control, Tab passes once through the browser's own controls and comes back; Q34, measured 2026-11-11); focus then returns to the chip |
| 16 | Input limits | Typing | Counter `n / 400`, in the `unverified` colour from 380 characters; Ask disabled while empty |
| 17 | Block not sent | A cited block the backend left out (over `EVIDENCE_MAX_CHARS`, Q30) | "This code is too long to show here. It is on GitHub." plus "View on GitHub". The panel itself has no line cap: no cited line is ever hidden (Q34 amendment, 2026-11-11) |
| 18 | Answer typography specimen | Mock | Headings, lists, inline code, a code fence, bold, and citations inside each of them. Also the input of the injection test (Q18) |
| 19 | Not found | 404 `not_found` (the repo stopped being featured) | "<repo> is no longer available here." The repo list is refreshed |

Behaviour added with the inventory:
- **Repo switching** resets the view, and a response still in flight for the old repo is
  ignored (test).
- **Submit is disabled while loading** (test: Enter does nothing).
- **The featured-repo list ships as static data**, so the first screen works with the backend
  down; `/repos` only refines it.
- **A controls check:** theme toggle, repo picker, Ask button, chips, panel close (keyboard and
  pointer).
- **Copy rule:** don't open several messages with the same word ("Couldn't…").

**Screenshots per review round:**
- States 1, 10, 11 and 15 at every width (390, 768, 1440) and both themes.
- All other states at 1440 light, 390 light and 1440 dark.
- 768 also for 12 and 13.
- Claude reads tiled contact sheets first and opens full PNGs only for flagged states.
- Review checklist item (from grading the fixture): adjacent citation chips ("[3] [4]") need
  visible spacing between them.
- Review checklist items (from my manual sheet check, 2026-11-11, iPhone 16 393x852):
  - only ~13 code lines show in the open sheet; the header and the citation list (up to 40%)
    take the rest. Decide here: keep, or shrink the list on mobile;
  - a chip can wrap to the start of a line, apart from the word it cites ("[2]" under "oldest
    to newest"). Decide here: keep, or keep each chip on the same line as the word before it;
  - the open chip's highlight is a little taller since the step 2 fix (Q38);
  - on mobile, the default citation's chip is highlighted though the sheet is closed.

**Round 1 (2026-11-11, 102 shots; mentor saw the findings table; my decisions):**

| # | Finding | Decision |
|---|---|---|
| F1 (High) | At 1024 the code panel's widest line widened its grid column and crushed the answer (~27 chars/line, overlap in state 13); at 1440 a ~300-char line made the page scroll sideways (2900 px) | **Fixed:** `minmax(0,53fr)`/`minmax(0,47fr)` and `min-w-0` on the aside. e2e regression at 1024 and 1440 with the long-line mock (now in `tests/e2e/mocks.ts`): no page scroll, reading column >= 440/600 px at ~53%, no overlap, the panel scrolls and reaches the line's end. 1024 (Q36) is re-judged in round 2 |
| F2 (Med) | Reading measure ~85 chars at 1440, ~95 at 768 (target 45-75): `66ch` resolved in the wrapper's interface font | **Fixed:** `--container-measure: 30.5rem`, aiming at 62-68 serif chars; round 2's notes measure it. Question and composer stay aligned |
| F3 (Med) | 320x568: the composer takes ~45% of the height | Keep 320 as is; round 2 adds 844x390 (landscape phone); compacting the composer under ~500 px height is decided after that |
| F4 (Low) | Offline message shown twice | **Fixed:** one owner per message, derived from state (`connectionNote()`): when the question failed unreachable, the composer line is quiet |
| F5 (Low) | Daily cap and model unavailable in red | **Fixed:** red and `role="alert"` only for failures on our side (`isAlarm()`): server errors and "can't reach" while online. Daily cap, model unavailable, not found and **offline (my decision)** are neutral in `role="status"`; the composer's waking/offline line is neutral, only "down" is red |
| F6 (Low) | The unverified "?" icon read like a no-entry sign | **Fixed:** a plain "?" (`[1?]`); the accessible name is unchanged |
| F7 (Low -> Med, mentor) | The unverified note split the sentence | **Fixed:** the note is a block after the paragraph or list item holding its chip; the chip still toggles it (e2e checks the sentence stays whole) |
| C2 (-> fix, mentor) | On a phone the default chip was highlighted while the sheet was closed | **Fixed:** highlighted and `aria-current` only while its sheet is open; on desktop the highlight is CSS (`lg:`), so no first-paint flash. Chips have no `aria-expanded` (they open a panel or dialog, not an expansion) |
| C6 (-> Med, mentor) | A chip could start a line apart from its word | **Fixed:** the space before a citation becomes a no-break space (visible gap kept); judged in round 2's 390 shots |
| C4 | Scrollbars hidden in headless shots | Round 2 adds states 1 and 12 at 1440 with visible scrollbars |
| C1, C5, C7, C8 | Chip spacing, sheet code area, open-chip highlight, queued sentence at 390 | Keep |
| C3 | Empty state's empty area | Slice 5 (suggested questions) |

**Round 2 (2026-11-11, 106 shots; the manifest was dirty: the scrollbar-project fix was committed only after the run, findings unaffected; my decisions):** confirmed fixed: F1 (no sideways page and no clipping in any shot; 1024 reads at 58-59 chars/line, was ~27), F2 (66-68 chars/line on desktop and 768, 47-49 on phones, 38 at 320), F4, F5, C2, F6, F7.

| # | Finding | Decision |
|---|---|---|
| R2-1 (High) | **C6's no-break space failed and regressed:** Chromium may break on either side of a chip (an atomic inline `<button>`), so chips still started lines at 390, and a lone "." sat on its own line after a chip, on the 1440 first screen | **Fixed:** the no-break space is gone; a rehype step in `Answer.tsx` wraps the word before a chip (or an inline `code` before it), the chip, adjacent chips and the punctuation right after into one `whitespace-nowrap` span. `span` is allowed only for this (markdown can't make one; raw HTML isn't parsed). Logic tests; re-judged in round 3 |
| R2-2 (Med) | 844x390 (landscape phone): the composer took half the height; the first screen showed no answer text | **Fixed:** a `short:` variant (max-height 500px): the composer isn't sticky there and drops its footer note. e2e at 844x390, with a 390x844 control (still sticky) |
| R2-3 (Low) | Visible Windows scrollbars at 1440: the reading column's bar sits against the panel border; nothing clipped | **Keep** |

**Round 3 (2026-11-11, 106 shots, clean manifest at `6529b72`):** no new findings. Notes: no sideways page, no clipping, no text under 12 px; reading measure unchanged (66-68 desktop/768, 58-59 at 1024, 47-49 phones, 38 at 320). R2-1 confirmed: chips stay with their words and following punctuation at 1440 (`newest" [2].` on one line), 1024, 390 and 320. R2-2 confirmed: at 844x390 the first screen shows the answer, with the composer after it. The three planned rounds are done. **Approved by me after my own look at the round 3 sheets (2026-11-11): step 4 is done.**

**Step 5, pass 1: `web-design-guidelines`** (2026-11-11; rules fetched fresh from vercel-labs/web-interface-guidelines; mentor-reviewed; my decisions):
- **Fixed:**
  - **W1 (High, WCAG 2.4.11, which axe doesn't check):** a focused element could sit under the sticky composer. `Composer.tsx` measures its height (plus the fade; 0 where it isn't sticky) into `--composer-height`, used as `scroll-padding-bottom` on `html` and the reading column. e2e: Tab to the last chip at 1440, 390 and 320x568.
  - **W2:** quiet hover states on Ask (new token `action-hover`, its label pair added to `check-contrast.mjs`), the outline buttons, chips, citation rows and the theme toggle. Tailwind 4's `hover:` applies only where hover exists.
  - **W3:** balanced h1.
  - **W4:** `theme-color` per system theme (follows the system, not the toggle; accepted).
  - **W5:** `translate="no"` on the code panel, its path, inline answer code, the wordmark and the repo picker.
  - **W6:** `name` and `autocomplete="off"` on the select and textarea.
  - **W8 (a):** the placeholder ends with "…" (an example question waits for slice 5's tested set).
  - **W10:** `overscroll-contain` on the panel's scroll areas.
  - Tabular digits on the counter, retry countdown and queue line.
  - Two new e2e checks: IME composition (Enter mid-composition doesn't submit) and the WCAG 1.4.12 text-spacing override (nothing clipped or overlapping at 1440, 390 and 390 with the sheet).
- **Done, as its own commit: W9.** Curly apostrophes in the page's own wording only: five messages in `messages.ts` and the ungrounded text in `App.tsx`. Model answers and code-like strings are never touched, and no UI string uses double quotes. The messages are named exports (`CANT_REACH_MESSAGE`, `OFFLINE_MESSAGE`, `DAILY_CAP_MESSAGE`, `serverErrorMessage()`) that the browser tests and screenshot states import. The logic tests that pin the wording keep it written out, plus one test that no message contains a straight `'`.
- **Kept:**
  - W7, the hand-built UTC date: `Intl` output can differ between Node's and the browser's ICU, which risks a hydration mismatch.
  - K1, Ask disabled while empty (`disabled`, not `aria-disabled`).
  - K2, sentence case.
  - K4, every code line rendered (bounded by the evidence cap).
  - K5, no `touch-action`.
- **Deferred:** K3, the URL reflecting state (a shareable `?repo=` in slice 5 or 6).
- **Not done (noted):** `prefers-contrast` and print styles; forced-colors is covered.

**Step 5, pass 2: `vercel-react-best-practices`** (2026-11-11; 70 rules against `components/`, `app/`, `lib/`; my decisions):
- **Fixed, R1 (Medium):** App's 1-second clock (waking, loading, busy) re-rendered the whole page every second, re-parsing the answer's markdown and rebuilding the code panel. `Answer` and `EvidencePanel` are now `React.memo`; their props are already stable then.
- **Kept:**
  - R2: the example fixture ships whole (11.9 KB, 1.7 KB of it record-keeping);
  - R3: small static SVGs inside components;
  - R4: every code line rendered, without `content-visibility`.
- **Also fixed, flagged by the IDE, not the review:** the chip-grouping step's `/(\S*)(\s*)$/` could backtrack super-linearly on long model text. It's replaced by a linear scan (`lastWord()`), and the grouping tests cover it.
- **Passes:** no request waterfalls, no barrel imports, flicker-free theme script, primitive effect dependencies, no components defined inside components, every listener cleaned up.
- **Step 5 is done.**
- Axe runs on every state in both themes.

**Done when:**
- locally I can pick a repo, ask, and click a citation that shows the right lines in the
  panel;
- the ask box is visible without scrolling at 1440×900 and 390×844 (screenshots);
- Playwright (mocked backend) passes: ask → answer → citation click, unverified citation,
  injection render test (Q18);
- I have approved a direction and the tokens;
- every state in the inventory has a reviewed screenshot;
- axe finds no serious violations;
- the web-design-guidelines review is done and I have decided on its findings;
- the first screen works with all network requests blocked (static repo list + example);
- no flash of the wrong theme on load;
- **(done 2026-11-11: with a broken `DATABASE_URL`, `/ask` returned 503 `application/json`;
  the page showed "The server couldn’t answer (request 97343f19). Try again." in red; headers
  `Access-Control-Allow-Origin: http://localhost:3000`, `Access-Control-Expose-Headers:
  X-Request-Id, Retry-After`, `X-Request-Id: 97343f19`, the same id as the page)** in a real
  browser, a forced server error reaches the page as JSON with CORS headers, **and
  the request id appears in the page** (mocks can't test allow-origin, Q38; the expose list is
  pinned by `test_api.py` and the mocks copy it). `Retry-After` in a real browser is verified in
  slice 4's live busy flow;
- the example fixture's grade (by me, with the date) is recorded here; **done 2026-11-11**:
  graded by Claude, spot-checked and agreed by me (Q37);
- `next build` and lint pass, with Next 16, Tailwind and TypeScript pinned to exact versions;
- the page has landmarks and a skip link.

**Build plan (approved 2026-11-03 with the mentor's amendments; decision Q34):**
Backend first:
1. **Panel data (Q30):** `public_view()` adds `blocks: [{path, start, end, content}]` (raw
   lines, no `182|` prefix): only the supplied blocks that contain a valid citation, each sent
   once, none when ungrounded. Each citation gets `block` (an index into `blocks`; null when
   unverified; the server already validated containment). A defensive cap on the total size
   of `blocks`.
2. **Example fixture:** `ask --save PATH` records the public view plus question, repo, commit,
   model, prompt version, date, generation parameters (temperature, reasoning setting, output
   limit), packer settings, token usage, retries and the run attempt number, and an empty
   `grade`. **The first live run is used, no re-rolls**; a re-run is recorded with its count.
   The fixture is **attempt 2**: attempt 1 (the slice 2 timing run, same prompt v3, 7/7 valid)
   was printed and not saved. If the two texts differ materially, that is noted here.
   **Done (2026-11-03):** `frontend/data/examples/pallets__itsdangerous.json` (generated
   2026-11-02 21:36 UTC, 382 output tokens, 4 blocks, 9.6 KB public payload). **Grade, by
   Claude (mentor review chat, 2026-11-03, at my request; corrected 2026-11-11, it was
   wrongly recorded as mine): correct; grounded yes; citations 7/7 strict. My spot-check:
   done 2026-11-11, I agree with the grade** (Q37). Every claim
   checked against the four supplied blocks; the mechanism is explained fully, but the
   practical rotation step (add the new key last, remove old ones later) is missing, so it is
   slightly incomplete. Attempts 1 and 2 differ only in minor ways, not materially (same
   claims; attempt 2 drops the closing paragraph and cites all of `verify_signature`,
   227-242, instead of the loop, 236-240). Temperature 0 did not make the two runs identical:
   regenerated answers won't match reviewed ones word for word (matters for slice 5). Since
   my spot-check, the label says "Checked by the author." Readable copy:
   `eval/results/m2_example_itsdangerous_grading.md`.
   **I grade it** (three columns: correct, grounded, citations valid; who and when). The page
   says "checked by the author" only once `grade.reviewer` is `"author"` (my spot-check done).

Frontend:
3. Housekeeping: `"strict": true`; gitignore `next-env.d.ts`; `react-markdown` pinned exactly
   (no `remark-gfm`); `@axe-core/playwright`; `next` and `typescript` pinned exactly (the pair
   that passes `next build`); `save-exact=true` in `frontend/.npmrc`; `package-lock.json` stays
   committed. **ESLint:** `eslint` + `eslint-config-next` pinned exactly, after checking which
   ESLint version `eslint-config-next` requires. **The theme script** keeps
   `dangerouslySetInnerHTML` for its one static constant string, with a single documented lint
   exception on that line; `scripts/check.ps1` fails if `dangerouslySetInnerHTML` appears
   anywhere else. **Slice 6 note:** a strict Content-Security-Policy would need a hash or nonce
   for that inline script.
4. `lib/`: `types.ts` (API contract incl. `blocks`, error JSON, `/status`); `api.ts` (fetch +
   classification: JSON error → typed; non-JSON or no response → waking/offline); `featured.ts`
   (static repo list + the example); **two small reducers** with discriminated unions:
   connection (`unknown | waking | up | down | offline`) and ask lifecycle
   (`idle | waiting | loading | answered | ungrounded | busy | error`; `waiting` holds a
   question submitted while the server wakes, and it is sent once). Long answers, long lines, many
   citations, truncation and input limits are rendering conditions or local form state, not
   machine states.
5. **Races:** every response carries its repo and a request counter; stale ones are dropped.
   No `AbortController` except on unmount. After a repo switch, Ask stays disabled until the
   old request settles ("Finishing the previous question"), because slice 4 allows one
   in-flight question per IP.
6. **Markdown safety:** `react-markdown` with a custom `urlTransform` that allows only
   `cite:<digits>` (the default sanitizer would strip `cite:`); an element allowlist, with
   disallowed elements unwrapped to their text; a `cite:n` with no matching citation renders
   as plain text; server URLs validated (`https://github.com/` prefix) and opened with
   `rel="noopener noreferrer"`; never `dangerouslySetInnerHTML` in components (lint rule).
7. **Components:** header, provenance, answer, chip (verified opens the panel; unverified is a
   button with an inline note), evidence panel (highlight + gutter bar, sticky line numbers,
   the whole block shown and the cited range scrolled into view, instantly under reduced
   motion; a defensive cap of ~300 lines with "View the rest on GitHub"), composer, status
   line, ungrounded and error views. **Mobile sheet:** native `<dialog>` with `showModal()`,
   styled as a bottom sheet (max 80dvh), background scroll locked with
   `html:has(dialog[open]) { overflow: hidden }`; the same panel renders inline on desktop.
8. **Tests:**
   - Playwright with mocked `/status`, `/repos`, `/ask`: ask → answer → citation, unverified
     note, injection, repo switch mid-request, Enter while loading, keyboard-only flow +
     controls check, `<dialog>` (focus inside, Esc closes, focus returns to the chip), axe on
     every state in both themes.
   - Logic tests (Playwright's runner, no page, no new dependency): both reducers, `api.ts`
     classification, `urlTransform` and the URL validators.
9. **Screenshots and review:** `design/render-states.mjs` (the same mocks, the matrix above,
   contact sheets built by Playwright), 2–3 review rounds, then the two review-skill passes.

### [x] Slice 4 (M2c): queue and abuse controls
One FIFO over `/ask` paced by Groq headers + own output-token accounting (Q10), position and
estimated wait in `/status`, busy at ~60 s (or the slice 0 limit), per-IP limits in memory
with a salted hash (Q6, Q16), length limit, daily cap row in Postgres, daily outcome
aggregates, kill switch. Measure how often questions repeat; build in-memory live caches
only if they are common (R3). Also the Q40 requirements for `/status` (no-store, no `queue`
without `CF-Connecting-IP`, answered from memory). **Open (2026-11-11, my decision to defer):**
`/ask` has no fetch timeout in the browser (only the unmount abort); it waits until the server
or a proxy closes. Decide here, once the real queue bounds the wait: a timeout would need its
own outcome and wording, since an abort is now classified as "can't reach the server".

**Done when:** pytest with a fake clock shows a burst beyond capacity gets queue positions or
"busy", never an unexplained error; per-IP and daily-cap refusals are deliberate and return
friendly messages (per-IP is a 429); the kill switch returns its friendly message; Playwright
passes the busy and cap flows.

**Grilling done (2026-11-11, mentor-reviewed, my decisions): Q42-Q45.** The headline finding:
Groq's **200K tokens/day** for qwen (free tier, per organization) allows only ~65 questions/day
in total, so the daily token budget, not the request rate, is the binding limit. The build plan
follows from Q42-Q45. It includes the frontend work: the new outcomes, `service` on page load,
the strings in `messages.ts` with exact-text tests, and axe on each new state in both themes. The
Done-when proof is a deterministic burst test with a fake clock injected into the limiter and the
budget.

**Done (2026-11-12): built in the Q46 order, steps 1-9.** Done-when, point by point:
- **A burst beyond capacity gets positions or "busy", never an unexplained error:** the burst
  test (200 seeds x 4 distributions, fake clock, a fake Groq with the real limits) had 0 Groq
  rejections, 0 timeouts, FIFO, one question at a time, and a truthful `Retry-After` (Q46 step 5
  amendments 1-3).
- **Per-IP and daily-limit refusals are deliberate, friendly, and per-IP is a 429:** in the API
  tests and the contract file, and live (below). **The kill switch's message:** live (below).
- **Playwright passes the busy and cap flows:** `limits.spec.ts`, `ask.spec.ts`, axe on 5 new
  states in both themes; full `check.ps1` green.

**Step 9 live check (real backend, dev database, `npm run dev`; observations):**
- **A bug the offline suite missed, found and fixed:** the first live question waited in the
  queue until its floor and returned `timeout` after 66.6 s (0 tokens, refunded).
  `Limiter.ready_at()` read its own clock, a few microseconds after the pacer's `now`, so a free
  Voyage slot always looked "just in the future" and the empty line never started (the fake
  clocks in the tests return the same value, and the real-thread smoke test had no limiter).
  Fix: the pacer passes its `now` into `ready_at` (pacer and projection). Two regression tests:
  a limiter clock a hair ahead, and real clocks with a real `Limiter`.
- **One live question after the fix:** a cited answer; **10,069 ms** end to end (queue, embed,
  search, Groq), inside the 15 s `S` seed and the 25 s floor (one sample: slice 6 still sets
  both from the longest measured time); 2,715 tokens counted, Groq's real usage.
- **Paused** (admin `pause`, ~30 s for the `/status` copy): the composer line with the example
  sentence; a question refused once under the heading, composer quiet, no retry, "Show the
  example answer" brought the example and the line back; `resume`.
- **Per-visitor** (`per-ip 1`): "…Try again in about 24 hours." from the real `Retry-After`
  through CORS; restored to 50.
- **Daily limit** (`budget 0`): the long composer line, then the refusal once under the
  question; restored to 120,000. No limit check cost a token.
- **Screenshot round s4** (the new states): no new automatic notes. **F1 accepted:** at 320x568
  the daily-limit line (5 lines) covers the example below its question; it is one scroll away,
  and the pre-registered rule (<= 40% at 390x844, ask box in view at both sizes) passed.

### [ ] Slice 5 (M2d): pre-generated answers
Table + CLI to generate answers for my chosen questions through the live pipeline (Q13), a
review step, a local export script writing static JSON into `frontend/` (Q14), the
"pre-generated on <date> with <model>" label, SHA check.

**Done when:** every featured repo (dev DB for now) has 5–8 reviewed answers; clicking a
suggested question shows its answer instantly with zero Voyage/Groq calls; Playwright passes
"pre-generated answers with the backend down".

**Grilling done (2026-11-12, mentor-reviewed with additions, my decisions): Q47-Q55.** In
short: answers are generated and reviewed on the dev DB and shipped as committed JSON (prod
reuses them); I write the questions, expected chunks are confirmed and frozen before anything
runs; the packer re-run (Q28) comes first, under a rule fixed beforehand; failures are eval
findings and get replaced, never re-rolled; every stored answer passes an exact cited-lines check
against a fresh clone at the pinned SHA; each repo opens on its flagship with the other questions
listed below. Out of scope: `?repo=` and CodeAsk as a featured repo (both slice 6).

**Resolved (2026-11-12, mentor):** (1) the flagship rule was reworded, not the fixture: "correct"
with no omission flagged as material (Q48); the itsdangerous fixture qualifies. (2) The backend
config gains a pinned SHA per repo, and the drift guard compares slug and SHA (Q52).

**Build plan (draft, 2026-11-12; for mentor review):**
1. **Pinned SHAs and licences (facts; I run the commands).** Print each featured repo's
   `commit_sha` from the dev DB. A fresh clone at that SHA is the source for the expected chunks
   (Q48), the cited-lines check (Q51) and the licence line (Q55). The featured list moves to
   `frontend/data/featured.json` (slug, url, `commit_sha`), imported by `featured.ts`, so a
   pytest drift guard can compare it with `config.FEATURED_REPOS` without parsing TypeScript.
   **Mentor additions (2026-11-12):** a logic test that the JSON has the fields the code
   expects; the backend never reads the frontend JSON at runtime (tests only); the drift guard
   fails loudly, never skips, if the file is missing or the slugs or SHAs differ. The pinned SHA
   per repo goes into the backend config (`FEATURED_SHAS`, slug -> SHA; `FEATURED_REPOS` is
   derived from it), and ingesting a featured repo without an explicit ref defaults to its
   pinned SHA (Q52). **Pinned (2026-11-12, from the dev DB):** itsdangerous `672971d6…`,
   requests `3c7baaa0…`, express `1c6f1b0f…` (full SHAs in `config.py` and `featured.json`).
2. **Questions and expected chunks (frozen, Q48).** I write 5-8 questions per repo (itsdangerous:
   the fixture plus 4-7 more). Claude drafts expected chunks from the clone, I confirm, and both
   are committed (`eval/m2d_questions/<owner>__<name>.json`, one file per repo, with the SHA)
   before step 3.
3. **Packer re-run (Q49), retrieval only.** `m2_candidates.py` and `m2_pack_compare.py` take a
   repo and its questions file (one Voyage request per repo; no Groq). Apply the committed rule;
   record the table and the outcome here.
   **Done 2026-11-12: no cap / 2,000 kept.** Each run checked that the dev DB's commit equals the
   pin. Candidates are in `eval/results/m2d_candidates_<owner>__<name>_2026-11-12.json`. The
   slice 2 table re-ran unchanged and the regression test passes. Required chunks packed at 2,000:

   | Variant | itsdangerous | requests | express |
   |---|---|---|---|
   | hard cap 3 | 8/11 | 9/19 | 16/21 |
   | soft cap 3 | 9/11 | 9/19 | 16/21 |
   | cap 5 | 10/11 | 9/19 | 16/21 |
   | **no cap** | **10/11** | **9/19** | **16/21** |

   No capped variant packs more on requests or on express, so the default stays (a tie keeps
   it). The caps only change *which* express chunks are missing. **Why chunks are missing at
   no cap / 2,000** (from the candidate lists):
   - **Not retrieved (top 15)**, so no packer can help (M3 retrieval findings):
     - itsdangerous q4 `dump_payload` (`url_safe.py` isn't in q4's list);
     - requests q1 `Session.send`, plus part 1 of `Session.request` and parts 1-2 of
       `HTTPAdapter.send`;
     - requests q4 `prepare_request` and `Session.send`;
     - requests q5 `build_response`.
   - **Retrieved but over budget:**
     - requests q1 `get` (rank 14) and `request` (rank 8, 756 tokens);
     - requests q3 `resolve_redirects`, whose 3 parts rank 1, 2 and 7; it is fully packed at
       2,500;
     - requests q3 `get_redirect_target` (rank 8);
     - express q2 `app.set` (13) and `compileTrust` (15);
     - express q4 `lookup` (12) and `resolve` (10). Both are packed at 2,500 under every cap.
   - **Express q5 `compileTrust` (rank 6) is also a budget miss.** `--show q5` at 2,000 packs
     `application.js` 9-47, 85-141, 336-383 and 443-465, and `utils.js` 122-184, for an
     estimate of 1,930. Ranks 1-5 are about 1,130 tokens of chunk text; the estimate also counts
     each file's outline and the block framing. That left no room for `compileTrust` (175
     tokens), so the skip-and-continue packer took rank 7 instead (`app.enable`/`app.disable`,
     106 tokens). At 2,500 it packs as `utils.js` 122-214. Not a bug.

   **Other findings for M3:**
   - Express's `examples/` directory is indexed and takes slots in q1, q3, q4 and q6, because
     the ingest filters exclude tests and docs but not examples.
   - The `defineGetter(req, ...)` getters are chunked as `<module>` blocks, so their
     breadcrumbs carry no name.
   - requests' long functions are split into parts, and retrieval often finds only some of
     them.
   - Raising the budget to 2,500 would add 1 required chunk on requests and 2 on express, but
     lose 1 on itsdangerous. Tuning goes to M3 (Q42 and Q49 fix the budget for slice 5).
4. **Generation CLI** `python -m codeask.pregen <slug>` (Q50, Q53): embeds the repo's questions in
   one Voyage request, then for each question with no stored attempt runs `ask()` with a 90 s
   deadline, paced by the existing `Pacer` (headers + own output tokens; it waits instead of
   refusing). Errors with no answer text are re-run up to 2 times, each logged. Writes the
   `fixture()` record (plus the run log) to `frontend/data/examples/<owner>__<name>/<id>.json`,
   prints a running token total, and stops before a question that would pass `--max-tokens`
   (default 100K; failed runs count).
   **Built 2026-11-12** as `python -m codeask.pregen generate <slug>`; `verify` and `export`
   become sibling subcommands.
   - **Before it runs:** it refuses a questions file that isn't confirmed, or whose SHA differs
     from the pin or the DB.
   - **Which entries:** it answers each `questions` entry whose answer file and
     `eval/results/m2d_failures/` file are both absent. A replacement is a reserve moved into
     `questions` by a committed amendment.
   - **Re-runs:** every run (answered or error, with tokens and whether they are estimated) is
     appended to `eval/results/m2d_runs_<owner>__<name>.jsonl`, so the 2-re-run limit survives
     restarts. A third error stops the run.
   - **Errors:** a Groq error, timeout, deadline, network or DB error can be re-run. Anything
     else is a bug and isn't re-run. Groq's daily limit (a 429 asking for more than 120 s) stops
     the run.
   - **Tokens:** the guard uses the same per-question reserve (3.5K) as the API. A failed run
     counts the API's 3.3K estimate if Groq was called.
   - **What it writes:** the answer JSON carries `question_id` and `runs`. The full result (raw
     answer, whole context, dropped chunks) goes to `eval/results/m2d_raw/<owner>__<name>/` for
     grading and M3, and never ships.
   - **itsdangerous q1** is the existing fixture, copied byte for byte to
     `frontend/data/examples/pallets__itsdangerous/q1.json`. The old file stays until step 8
     moves the import.
   - **Tests:** 16 offline tests in `backend/tests/test_pregen.py`.
5. **Cited-lines check** `python -m codeask.pregen verify <slug>` (Q51): a fresh clone at the
   pinned SHA (`ingest.clone`, no symlinks followed); every block's lines must equal the file's
   lines `start..end` exactly (split on `"\n"`); the result (ok, SHA, date) is written into each
   JSON. Re-run on all stored answers after any chunker, packer or prompt code change (Q50).
   **Built 2026-11-12.**
   - **Independent of the DB:** it uses no API and no database. The clone goes into a
     temporary folder, deleted afterwards, and must come back at exactly the pin.
   - **What it checks:** each shown block (`response.blocks`, the shipped evidence) and the
     record's `commit_sha`.
   - **How files are read:** as ingest reads them (strict UTF-8, BOM stripped, CRLF -> LF), so
     "exact" means exactly what the model saw.
   - **Path safety:** a path with `..`, `.`, a backslash, a leading `/`, or a symlink anywhere
     on the way is a failure, never followed.
   - **The record:** the result is written as `lines_check`: `ok`, `commit_sha`, `checked_at`,
     the block count and any problems. The command exits non-zero if any answer fails.
   - **Tests:** 15 more offline tests.
6. **Grading (Q51).** Claude drafts claim-by-claim grades and marks the 2-3 riskiest claims
   (`reviewer: "claude"`); I spot-check and flip to `author`. A failed answer moves to
   `eval/results/m2d_failures/` with its grade; its replacement question is committed before it
   runs. Counts per repo are recorded here.
7. **Export** `python -m codeask.pregen export <slug>` (Q47, Q52): writes the repo's
   `index.json` (passed answers in order; the flagship first, Q48), and refuses an answer whose
   SHA differs from the dev DB or `featured.json`, whose cited-lines check isn't ok, or that has
   no passing grade. `check.ps1` (pytest) validates every shipped file's shape offline, the SHA
   pins and the drift guard.
   **Built 2026-11-12.**
   - **It writes nothing** if any of these hold:
     - the pins disagree (config, `featured.json`, the dev DB);
     - an answer is for another commit, or names another question id;
     - an answer's `lines_check` isn't ok;
     - an answer has no grade, or an unknown grade value;
     - a stored question differs from the frozen one;
     - an answer exists for an id not in `questions`;
     - nothing passes.
   - **Left out and printed:** answers that don't pass, and questions not generated yet.
   - **`index.json`:** `{repo, commit_sha, exported_at, flagship, flagship_note, questions:
     [{id, question}]}`, flagship first, then question order. It carries the question text so
     the list can be drawn without loading every answer.
   - **Tests:** 19 offline tests for export. `backend/tests/test_examples.py` re-checks every
     shipped `index.json` (pin, frozen questions, every listed answer passes, flagship rule) and
     that each examples folder is a featured repo.
8. **Frontend (Q54).** Per-repo dynamic import of `index.json` and its answers (the default
   repo's set is imported statically, so the first screen needs no extra request). The flagship
   opens each repo; `SuggestedQuestions` lists the others below the answer in the scrolling
   column, also under live answers, hidden while loading; a click shows the stored answer at
   once (`aria-current`, focus to the new heading, scrolled into view, instant under reduced
   motion, the draft kept). Typed questions always go live. The "answered on its own" note under
   live answers. "The suggested questions still work." replaces the "example answer above"
   sentence (and the model-unavailable one), shown only when the list is on screen.
   **Mentor additions (2026-11-12):** (1) a failed dynamic chunk shows a calm message, keeps the
   current view and offers a retry; tested by aborting the chunk request (chunks are served from
   the same origin). (2) Rapid clicks on suggestions end on the last click (a request-id guard,
   as for live answers), with a test. (3) After the build, record the first-load size; if the
   default repo's whole set is heavy, import only its index and flagship statically and load the
   other answers on click. (Optional, not planned unless I choose it: prefetching other repos'
   chunks on picker focus.)
   **Plan review (2026-11-12, mentor; author's choices D1a, D2a, D3a):**
   - **D1, the bundle:** `pregen export` also writes `frontend/data/examples/sets.ts`.
     - It has one loader per exported repo, in a stable order, with a "generated, do not edit"
       header and a lint/format ignore.
     - The default repo's set is a static import; the others are dynamic, one chunk per repo.
     - pytest checks that it equals a fresh regeneration from the exported folders, that every
       repo in it is in `featured.json`, and that each `index.json` `commit_sha` equals
       `config.FEATURED_SHAS`.
   - **D2:** the "Show the example answer" button is removed. In those states the list is on
     screen and each item is a way back.
   - **D3:** the note under live answers reads "Each question is answered on its own; earlier
     questions aren't remembered."
   - **A repo with no stored set** (requests and express today, or a repo stopped by the stop
     rule) gets no stored answer and no list, only the composer. The loader returns "none"
     instead of throwing. Tested.
   - **The request-id guard:**
     - It covers repo switches: A to B to C ends on C, and a late B never overwrites it.
     - It covers a live question in flight at the switch: its answer never lands on the new
       repo's page (the existing `settling` state).
     - On a chunk failure, the selector keeps the repo whose content is on screen, and Try
       again retries the same switch.
   - **First-load size rule (fixed now):** record the gzip first-load JS for `/` before step 8
     as the baseline, then re-measure after step 11 with the real answers. If the default
     repo's set adds more than 30 kB gzip, load its answers lazily (I may change the number). A
     measurement now understates, because only q1 exists. **Baseline (2026-11-12, before
     step 8, `node scripts/first-load.mjs`): 216.8 kB gzip in 7 chunks.** It already includes
     the old single fixture (today's q1).
   - **Before deleting the old fixture:** grep its path in `tests/e2e/mocks.ts`,
     `design/screen-fixtures.ts` and `design/render-states.spec.ts`, then diff it against the
     exported q1. Expected differences: `lines_check` (step 5), and `grade.unsupported` and
     `grade.omission` (step 7). q1 is the fixture copied unchanged, so it has no `question_id`
     or `runs`. That differs from the mentor's expected list; flagged. **Checked 2026-11-12:**
     the path appears only in `lib/featured.ts` (`EXAMPLES` is used in `App.tsx` and
     `tests/e2e/mocks.ts`), not in `design/`. The key-by-key diff shows exactly those three
     additions.
   - **`aria-current`:** only when a stored answer is on screen, never for a live answer, even
     one whose text matches a suggestion. The focus target, the question heading, has
     `tabindex="-1"`.
   - **Accepted, not mitigated:** a click on a suggestion replaces a live answer that cost one
     of the visitor's daily questions.
   **Built 2026-11-12:**
   - **The bundle:** `lib/stored.ts` statically imports the default set (`DEFAULT_SET`) and
     uses `LOADERS` from the generated `sets.ts` for the rest.
   - **`loadSet()`:** returns the set, or "none" for a repo with no export; it rejects only on
     a chunk failure.
   - **App state:** a per-repo set cache, the picked id (null = flagship), and the pending
     switch with its id guard.
   - **A pending switch:** the selector shows the new repo, Ask waits, and the composer line
     says "Loading the suggested questions…". A failed chunk keeps the repo on screen and offers
     "Try again" for the same switch.
   - **New reducer event `show_stored`:** it returns a settled answer, refusal or error to idle,
     and does nothing while a question loads, waits or settles.
   - **New component `SuggestedQuestions`:** buttons with `aria-current`, marked by a bar and a
     weight change, not colour alone.
   - **Messages:** `SUGGESTIONS_STILL_WORK` and `modelUnavailableMessage`; `errorMessage()` now
     takes `listShown`, so refusals under the list add the sentence.
   - **Removed:** the old fixture, `EXAMPLES` and the "Show the example answer" button.
   - **Lint:** `eslint.config.mjs` ignores `data/examples/**/*.ts`.
   - **Tests:** existing e2e and logic tests updated. New: `tests/logic/stored.spec.ts`, 3
     `show_stored` reducer tests, 6 e2e tests in `tests/e2e/suggestions.spec.ts`, and pytest
     checks of the generated modules.
   - **Pending until answers exist (step 11):** the e2e cases that need two stored answers or a
     second exported repo (rapid picks, A -> B -> C, a failed chunk), and the first-load
     re-measure.
   - **Checked 2026-11-12:** `check.ps1` full run: 470 backend, 90 logic and 122 e2e tests
     pass, including 6 new e2e tests for the suggestions. First load is **217.9 kB** gzip in 8
     chunks: +1.1 kB over the baseline, with only q1 in the set (Turbopack puts the set in its
     own chunk, which the page still loads first).
   - **For step 9's review:** in the answered state, axe reports `elmPartiallyObscured`
     "incomplete" on `#suggested` (the list scrolls under the sticky composer). It's
     "incomplete", not a violation, like the existing chip and fade cases. Check it in the
     screenshot round.
9. **Tests and review (Q55).** e2e: a click serves the stored answer with zero API calls;
   pre-generated answers with the backend down; repo switch opens the flagship; list hidden while
   loading; a typed suggested question goes live; keyboard/focus/scroll flow. Axe on the new
   states in both themes and forced colors. One `round-s5` screenshot round (Q41 matrix).
10. **Licence line (Q55)** in the README's "How it works", from each LICENSE at the pinned SHA.
11. **Generation run** on the dev DB, at least 24 h before launch (Q53), then the Q42 budget
    raise; PLAN.md records counts, tokens and findings.

### [ ] Slice 6 (M2e): deploy
**Gate from slice 4 (Q44):** before going public, compare the client IP the API sees with my
real address from two networks, and send one request with a forged `CF-Connecting-IP` to
confirm Render's edge overwrites it. A custom domain or a proxy of my own could otherwise make
every visitor share a few addresses and break the per-IP limit.

Prod Neon project + API role (Q7), `.env.prod` with an explicit flag and host confirmation,
gitleaks scan → CodeAsk public → pinned release commit (Q12), ingest the featured repos at
their pinned SHAs (slice 5's reviewed answers ship unchanged, Q47), new Render + Vercel services with final names, CORS to the
Vercel origin, cold-start UX (Q14), privacy footer (Q16, R11), delete the spike services and
rotate the keys set there, freeze `spike/m2/` (Q19). Link-preview metadata (title,
description, Open Graph image) for sharing the URL (moved here from slice 3).

**Done when:**
- the `db` test proves the API role cannot write content tables or delete;
- the deployed API exposes no ingestion route (checked against its route list);
- after the prod ingest, each featured repo's `commit_sha` from `/repos` equals its pinned SHA
  (Q52);
- 3 cold starts after ≥ 15 min idle are recorded from the deployed page (time until
  "waking up" turns ready, and time to the first answer), and the UI never shows a raw error
  during them;
- the manual smoke checklist passes on the public URLs (ask, citation, unverified display,
  pre-generated, busy, cap via kill switch, and the sticky ask box with the on-screen
  keyboard open on a real phone);
- Render's Billing page shows usage within the free limits a week after launch;
- `MIN_TIME_TO_START_S` and `PROJECTED_SERVICE_SEED_S` are set from the **longest** measured
  live service time (the slice 4 live check and the first real traffic) plus a margin, not only
  the p95, and not the 25 s / 15 s guesses: the projection is an upper bound only while the
  seed really is one (Q46 step 5 amendments 2 and 3);
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
| Q7 | **Data topology:** a **separate Neon project** for the demo. The API's DB role has SELECT on content tables and INSERT/UPDATE only on its own `usage` table (amended 2026-11-11, Q46: the `usage_*` tables; the API also UPDATEs `usage_settings`, so a compromised API could change the budget or un-pause: accepted, since the stakes are the Groq quota and content tables stay read-only. The API never runs DDL in production; the schema is created by the owner role in slice 6). Prod URL lives in a gitignored `.env.prod`, loaded only by an explicit flag; ingest against prod prints the DB host and asks for confirmation. Featured repos are re-ingested into prod (minutes); prod has its own embedding store | Free compute (100 CU-h/month) and storage (0.5–1 GB, sources conflict) are per project, shared by its branches, so dev and M3 runs can't suspend the demo | Same DB; a branch of the dev project; a fully read-only role (breaks the DB-backed daily cap) |
| Q8 | **Single-turn:** each question answered on its own; the UI says so. After an answer, follow-up chips built from the cited chunks' breadcrumbs with fixed templates (no LLM, no history). **Amended 2026-11-12 (Q54):** the follow-up chips were never built; the suggested-questions list replaces them, and only the "answered on its own" note is built (slice 5) | History costs Groq tokens per minute and needs query rewriting for retrieval | Follow-ups with history (M4 topic) |
| Q9 | **Citation contract:** inline `[path:start-end]`, parsed by the server. Valid only if the path matches a supplied block and the range lies wholly inside its supplied lines (**blocks after merging**; partly outside = unverified, no clamping). Valid ones become links; invalid ones are shown as "unverified" and counted (M3 metric). Zero valid citations means "couldn't ground this in the code" plus the "possibly relevant" files. No regeneration in M2 | Inline keeps each claim next to its source; markdown in JSON strings is fragile; regeneration costs a second Groq call | JSON output; silently dropping invalid citations; regenerate once |
| Q10 | **Queue:** one FIFO over the whole `/ask` path, paced by Groq's headers (`*-tokens` = TPM, `*-requests` = RPD per Groq docs) **plus our own output-token accounting** from each answer's `usage` (qwen's 1,000 output tokens/min is not in the headers). Busy at ~60 s estimated wait (120 s requests proven in slice 0); the UI shows position and estimated wait. Optional small exact-match answer cache (repo, commit, normalized question, prompt version, model), labelled "answered earlier", only if it stays small | A cache hit skips Voyage but never Groq, so Groq is the real bottleneck | Voyage-only queue; spinner without position |
| Q11 | **Context packing:** budget ~2–2.5K tokens (config), counted on the numbered display. Retrieve ~12–15 candidates, pack greedily by rank, per-file cap 2–3 chunks (**counted before merging**), merge adjacent same-file chunks, present grouped by file in line order. Class outlines only when a header chunk is retrieved, size-capped. M3 tunes the values | ~2–2.5K context keeps ~3 questions/min under 8K TPM; the cap fights M0's near-duplicates | Fixed k=5; ~3K budget |
| Q12 | **Featured repos:** itsdangerous, requests, express, and CodeAsk itself, **pinned to a release commit** and refreshed only at milestones. Before featuring CodeAsk: make it public after a full-history secret scan (gitleaks). TableTalk and flask optional later | Python + JS, small to medium, plus a self-referential demo | Featuring CodeAsk at `main` (answers go stale every commit) |
| Q13 | **Pre-generated answers:** ~5–8 questions per repo, chosen by me, answered by the live pipeline, each answer and its citations reviewed by me. Stored with commit SHA, prompt version, model id and date; labelled "pre-generated on <date> with <model>"; shown only if the SHA matches the repo's current one (re-ingest ⇒ regenerate). Generation counts against the daily cap, serving doesn't. **Amended 2026-11-12:** the SHA match is a pinned SHA checked in tests and at export, not at runtime (Q52); generation runs outside the live budget table, which I lower by hand on generation days (Q53); the "LLM-written questions" rejection is relaxed for slice 5's set: proposed by the mentor chat before any answer existed, selected and accepted by me (Q48 amendment) | Instant, free answers that are honestly labelled | LLM-written questions; serving stale answers |
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
| Q28 | **Packer default: no per-file cap, budget 2,000 (provisional).** Overrides Q11's cap. `PER_FILE_CAP` stays a parameter (default `None`) for the M3 ablation. **Evidence is one small repo** (itsdangerous, 8 questions, 12 required chunks): in slice 5, re-run `eval/m2_pack_compare.py` on requests and express using the pre-registered expected chunks of their suggested questions; if the result flips, revisit the cap (per repo or in M3). Q6 `derive_key` not being in the top 15 is an M3 retrieval finding. **Why 2,500 packs fewer than 2,000:** greedy skip-and-continue packing is not monotone in the budget. In Q5 at 2,000 the Signer class header (`signer.py:76-127`, ~870 with its 37-line docstring) doesn't fit and is skipped, leaving room for `derive_key` and `verify_signature`; at 2,500 it fits and `derive_key` no longer does. Only a stop-at-first-misfit greedy is monotone, and it would lose both at 2,000. So there is no "more budget never removes a chunk" test; a test pins the skip behaviour instead. **Slice 5 re-run (Q49, 2026-11-12): the result did not flip.** On requests and express, every variant ties at 2,000, so the default is kept | Only no cap at 2,000 packs every retrieved required chunk (11/12); it's also the simplest variant (Q20 rule). M1 chunks don't overlap, so the near-duplicates the cap targeted (M0) are gone; on a small repo the answer genuinely sits in one file and a cap pushes weaker other-file chunks in | Hard cap 3 (fails the Q5 regression check); soft cap 3 (same); cap 5; budget 2,500 |
| Q29 | **Design brief** (slice 3 grilling, 2026-11-03): see the brief under slice 3. Recruiters lead; a pre-generated example answer with citations on the first screen; precise, calm, quietly editorial; system theme + toggle; side by side on desktop with the first valid citation pre-opened; bottom sheet on mobile, closed by default; text wordmark + bracket glyph | The first screen must show value with zero interaction for a recruiter skimming for ~30 s | A landing-page hero; an empty ask box first |
| Q30 | **The code panel's lines travel with the answer:** `/ask` (and the example fixture) includes the supplied blocks that contain at least one valid citation, nothing else. Amends Q5's "cited ranges plus a little context": a block is bounded by the context budget (~2K tokens, a few KB), never a whole file | The panel and the pre-opened citation need the lines; the blocks are exactly what the model saw, so the panel shows the real evidence | A `files` table; fetching lines from GitHub in the browser; sending all supplied blocks |
| Q31 | **Visual direction A, "Marked copy"** (step 2, 2026-11-03; mocks in `frontend/design/directions/`, rendered by `frontend/design/render-directions.mjs`): the answer set as a typeset page (Newsreader serif; Instrument Sans for the interface; Fragment Mono for code) on cool grey-green paper with blue-black ink; citations as small bracketed footnote figures; **the active footnote and its cited lines share one highlighter yellow** (kept a true highlighter, dark ink on yellow, in dark mode too). From C: chips get a larger tap area on mobile (≥ 24 px) without looking bigger | The only direction whose memorable element is the product's own idea (claims tied to marked evidence); matches "precise, calm, quietly editorial, citations as footnotes" most directly | **B "Bracket"** (Schibsted Grotesk, verdigris, a drawn bracket in the code gutter): cohesive brand story but reads as a generic developer tool, and the gutter bracket is too subtle to carry the design. **C "Two rooms"** (Atkinson Hyperlegible, code on a bottle-green slab): clearest split and most tappable chips, but the dark rounded slab drifts to the familiar IDE look and is the least editorial |
| Q32 | **Fonts: Newsreader without the optical-size axis** (step 3, 2026-11-03). `next/font` self-hosts, Latin subset, `display: swap`, upright only (italics synthesized): Newsreader variable weight, Instrument Sans variable weight, Fragment Mono 400. All three Latin files are preloaded, mono included (the code panel is above the fold). **Measured** (`next build`, `.next/static/media`): with `opsz` the preloaded Latin files were 128.8 + 29.2 + 14.8 = **172.8 KB**; without it 56.8 + 29.2 + 14.8 = **100.8 KB** (−72 KB, −42%). Other `.woff2` files (latin-ext, vietnamese, cyrillic-ext) are emitted but only downloaded if the page shows those characters. **Decision rule, fixed before comparing:** I screenshot the 36 px question and 18 px body with and without `opsz` at desktop and mobile widths, and keep it only if I see a difference I care about. The difference was mostly width (with `opsz`: slightly narrower and crisper, one fewer line per paragraph on mobile), not worth 72 KB on a recruiter's first visit | Payload on the first visit; the design's distinctive element is the highlighter, not optical sizing; the headline's tracking (−0.015 em) recovers some crispness for free | Keeping `opsz` (172.8 KB); static weights 400 + 500 |
| Q33 | **Tokens approved** (step 3, 2026-11-03): semantic colour tokens in `frontend/app/tokens.css` (`page`, `panel`, `text`, `text-muted`, `rule`, `control-edge`, `citation`, `focus`, `evidence`, `on-evidence`, `evidence-bar`, `unverified`, `error`, `action`, `on-action`, `elevation-sheet`), light and dark; the fixed scale in the `@theme` block of `frontend/app/globals.css` (type 12/14/16/18/21/24/36, a 66ch measure, radii 2/6/12 by role). Tailwind **4.3.3** (`tailwindcss` and `@tailwindcss/postcss` pinned exactly; `postcss` 8.5.32); Tailwind colours read the token variables, so no `dark:` classes. Theme set before first paint by a `<head>` script (try/catch around `localStorage`, sets `color-scheme`; `suppressHydrationWarning` on `<html>`). **With the gutter bar:** cited lines get a left border in `evidence-bar` (a border survives forced-colors mode; a background doesn't). **Contrast** (`node design/check-contrast.mjs`, every pair passes in both themes): text pairs ≥ 4.5:1 (lowest: `text-muted` on `panel`, 5.22 in light); UI parts ≥ 3:1 (lowest: the dark `evidence-bar` 3.06 against both the panel and the highlighter, so re-run the check after any change to the dark `panel` or `evidence`); for information, the light highlighter vs the panel is 1.12:1, which is why the bar, bold line numbers and the header text also mark the cited range | WCAG AA without exceptions; semantic names let the design change without touching components | Raw colour names; a background-only highlight |
| Q34 | **Slice 3 build plan** (2026-11-03, mentor amendments; full plan under slice 3): `blocks` as a separate list with a `block` index on each citation and a payload cap; a fixture from the first live run, graded by me; two small reducers (connection, ask lifecycle) instead of one machine for 19 states; stale responses dropped by repo + request counter, Ask held until an old request settles; `urlTransform` allowing only `cite:<digits>`; native `<dialog>` for the mobile sheet (Tab measured 2026-11-11: sheet x9, browser UI, sheet; never the page behind; Q39); the whole block shown, scrolled to the cited range (the ~300-line cap was removed 2026-11-11 so no cited line is ever hidden, Q39); logic tests on Playwright's runner | Smallest design that covers every state honestly; one in-flight question per IP (slice 4); no new UI dependencies | One reducer for all states; a hand-built focus trap; truncating blocks over 60 lines; `AbortController` on repo switch |
| Q35 | **TypeScript 6.0.3, not 7** (slice 3 build step 3, 2026-11-03). Lint failed on TypeScript 7.0.2 with "typescript-eslint does not support TS 7.0" (`eslint-config-next` 16.4.4 pulls in `typescript-eslint` 8.72.1, which supports TypeScript ≥ 4.8.4 < 6.1; support for ≥ 7.1 is tracked upstream). Exact pins now: `next` 16.4.4, `typescript` 6.0.3, `tailwindcss` / `@tailwindcss/postcss` 4.3.3, `eslint` 9.39.5, `eslint-config-next` 16.4.4, `react-markdown` 10.1.0, `@axe-core/playwright` 4.14.0, `@playwright/test` 1.64.1; `save-exact=true` in `frontend/.npmrc`. `next build` passes in strict mode and lint is clean. `npm audit --omit=dev`: **0 vulnerabilities** in what ships; 16 moderate ones are all in dev tooling. npm marks ESLint 9.39.5 as no longer supported: revisit ESLint 10 (and TypeScript 7) in slice 6, once `eslint-config-next`'s plugins and `typescript-eslint` support them. Also: the dev server writes `.next/dev/types`, which `next build` type-checks, so delete `.next` after removing a route | TypeScript 7 arrived by accident in slice 1; its main gain (compile speed) barely matters here, and lint with TypeScript rules is a Done-when item | Running a TypeScript 6 copy side by side for lint only; dropping the TypeScript lint rules |
| Q36 | **Side by side starts at 1024 px** (slice 3, the built page, 2026-11-11), not the mocks' 760 px: tablets get the bottom sheet. Confirm in the 768 and 1024 screenshots | Safer layout on tablets: at 760-1023 px the reading column and the code panel would both be cramped | 760 px, as in the direction mocks |
| Q37 | **Example fixture grade provenance** (2026-11-11): the itsdangerous fixture was graded by Claude in the mentor review chat on 2026-11-03 at my request, not by me; PLAN.md and the fixture had wrongly recorded it as mine. The fixture's grade has one typed field, `grade.reviewer: "claude" | "author"` (mentor review of step 2, chosen by me as option (a); it replaced a free-text `by` plus an `author_checked` flag, which could contradict each other). The label is derived from it: `claude` reads "Checked against the cited code by Claude; not yet reviewed by the author.", `author` reads "Checked by the author.", no grade gives the date sentence only; who, where and what's pending stays in the free-text `note`, which the label never shows. It switches to `author` only after my three spot-checks (the `reversed(self.secret_keys)` loop, the "oldest to newest" comment, `return self.secret_keys[-1]`). **Done 2026-11-11:** I spot-checked all three against the code at `672971d` and agree with the grade, so the fixture says `reviewer: "author"` and the label reads "Checked by the author." **Also: temperature 0 is not reproducible on Groq** (attempts 1 and 2 differ in wording and citation 5's range), so slice 5's reviewed answers must be stored, not regenerated | An honest label is the point of the product; a recruiter-facing page must not claim a human check that didn't happen | Leaving "checked by the author"; dropping the check sentence from the label; `by` + `author_checked` (two fields that can disagree) |
| Q38 | **Browser tests: approach** (step 2, 2026-11-11, mentor amendments). A separate `frontend/playwright.e2e.config.ts`, because `webServer` starts for every run, even `--project=logic` (**measured** with a scratch config). It runs `next build && next start` on port 3100, built into `.next-e2e` (`distDir` from `NEXT_DIST_DIR`; the two `.next-e2e` type globs are in tsconfig by hand, since `next build` would otherwise add them) against `http://api.test`. Chromium only, with mobile emulation for the sheet. Mocks (`tests/e2e/mocks.ts`): a handler table, unmocked API calls and any third-party request fail the test, shapes taken from the backend source. **CORS in mocks, measured on Playwright 1.64.1 + Chromium: a `route.fulfill` reply without CORS headers still reaches the page (GET and JSON POST), and the preflight never reaches `page.route`, so allow-origin can't be tested through mocks. But Chromium still hides response headers that aren't exposed:** the busy test read no `Retry-After` (and fell back to 60 s) until the mock sent `Access-Control-Expose-Headers`. So every mock reply sends the same expose list as `app.py`, and `backend/tests/test_api.py` pins that list on the server (corrected 2026-11-11; the first reading, "mocks can't verify exposed headers", was wrong). Time via `page.clock` (`pauseAt` + `runFor`; exact 11 s / 12 s boundaries measured). Axe: any violation fails, "incomplete" results are logged for one review. **Review done (2026-11-11, mentor-approved):** 0 violations in 13 states x 2 themes. Every incomplete result was `color-contrast` that axe couldn't measure (`pseudoContent` from the composer's fade `::before`; `elmPartiallyObscured` from text under the sticky composer or a scroll edge, and from the open chip). Every flagged element sits on a pair `design/check-contrast.mjs` verifies, which already covers the focus outline on page and panel; there is no hover colour state. The inferred causes were tested: **confirmed** that the fade lies entirely above the form and removing it removes `pseudoContent`, and that inline answer code has no background. The open chip's first suspect (its `::after` tap area) was **wrong**: axe's `relatedNodes` named the chip itself, and it measured as a 15px text box under a 12px highlight (2px over the top, 1px under), so glyphs overflowed their background (dark ink on the dark page in dark mode). **Fixed** (my decision) with `py-[0.25em] -my-[0.25em]` in `Chip.tsx`: the highlight grows, the line layout doesn't move. Tested in both themes. Table in the header of `frontend/tests/e2e/a11y.spec.ts`. `scripts/check.ps1` runs the browser tests unless `-Quick`. **Gotcha:** `next build` type-checks the tests too, and a type error shows only as "[WebServer] Failed to type check"; `npx tsc --noEmit` prints the real error | Tests what ships; every state and race reproducible; the logic tests stay fast | An e2e project in `playwright.config.ts`; the dev server; `setOffline` + reload for "network blocked" (with no service worker it tests Chrome's error page); allow-origin headers in the mocks (not enforced under Playwright); WebKit/Firefox until the slice 6 phone check |
| Q39 | **Step 2 review outcomes** (mentor review, 2026-11-11). **(1) Q34 amendments.** The mobile sheet keeps the native `<dialog>`, with no custom focus trap. Measured: Tab from the sheet's 10 controls went sheet x9, browser UI (`activeElement` = `body`), sheet; it never reached the page behind, which is inert. State inventory row 15 now states that requirement. Q34's ~300-line panel cap is **removed**: it hid any citation past line 300 of a block. Rule: no cited line is ever hidden; the only size bound is the backend's `EVIDENCE_MAX_CHARS` (row 17). Tested with a 400-line block cited at 350-352. **(2) Q36 measured:** at 1023 px a chip opens the sheet; at 1024 px the side panel shows and no sheet opens (`layout.spec.ts`). Reflow at 320x568: no horizontal page scroll, and the ask box works (WCAG 1.4.10). **(3) Screenshots (step 4)** are a Playwright file in its own config, run by `npm run screens` and not by `check.ps1`. They wait for `document.fonts.ready`, with animations disabled and a fixed clock, and go to the gitignored `frontend/design-review/` (as planned, not the suggested `design/screens/`). Contact sheets are rendered from an HTML page. They are review material, not assertions. **(4) My manual sheet check** (Chrome device mode, iPhone 16 393x852, both themes): opening, the 138-142 highlight, scrolling in both directions with the page behind still, Close and Esc, chip tapping all work. **Decision:** a tap on the dimmed backdrop now also closes the sheet; only a click on the `<dialog>` itself outside its box counts, so Enter on a button inside doesn't (tested in `mobile.spec.ts`). The code area's size and chip wrapping are deferred to the step 4 review checklist | A verified citation the reader can't see defeats the product; the native dialog meets WCAG's no-keyboard-trap rule without code that fights the platform | A custom focus trap; keeping the 300-line cap, or windowing it around the cited range; `design/screens/` |
| Q40 | **State 5 "Queued": provisional shape and behaviour** (step 3, 2026-11-11, mentor-reviewed, my decisions). **Shape (PROVISIONAL, slice 4 confirms):** `GET /status` gains an optional `queue: { position, wait_s } \| null`. `position` is the caller's own place (1 = being answered, 2 = one ahead); `wait_s` is the server's estimate (at most ~60, since above that `/ask` says busy, Q10); absent or null = nothing waiting. **Caller = hashed IP (A):** Q6 allows one question in flight per IP, so "my question" is unambiguous and nothing new goes on the wire. **Slice 4 must:** send `Cache-Control: no-store` on `/status` (now per caller); return no `queue` when there's no `CF-Connecting-IP` (direct onrender.com, local dev); answer `/status` from memory, never waiting on the limiter's lock, a DB connection or an LLM call; leave per-IP room for one `/status` every 3 s. **Frontend:** validated once in `api.ts` (position an integer 1..99, else no queue; `wait_s` finite >= 0, else the position without seconds; never breaks the rest of `/status`). While a question is loading: first poll ~1 s after asking, then every 3 s (chained timeouts, an in-flight poll aborted when the request settles); stops at position 1 or when the request settles; never while idle; a failed poll is ignored (the `/ask` outcome decides). Position >= 2 shows "2nd in line, about 40 seconds." (wait rounded up to 10 s, never 0) in a visible line with `aria-live="off"` that updates every poll; a visually hidden `role="status"` changes only when the position changes. "Still working…" (12 s) restarts only on the change from >= 2 to 1. Implemented as data on `loading` (`queue`, set by a `queue_update` event carrying the request id; stale ones dropped), not a new reducer state (Q34); inventory row 5 stays, and axe and the screenshots still list it as a state. **Built 2026-11-11:** `readQueue`/`pollQueue` in `api.ts`, `queue_update` in `state.ts`, the wording in `messages.ts`, polling and the split live region in `App.tsx`; 15 logic tests (`tests/logic/queue.spec.ts`) and 8 browser tests (`tests/e2e/queue.spec.ts`, plus axe on the queued state in both themes). Polling is measured in the page itself: none while idle, +1 s, +4 s, +7 s, none after position 1 or when the question settles | `/status` already exists for this (slice 4 text); "2nd in line" is more honest than a global count; the split live region keeps the seconds current without chatter | **B:** a client ticket sent with `/ask` and polled via `/status?ticket=` (the fallback if IP identity proves unreliable); **C:** a global queue length only; freezing the wait at each position change; restarting the escalation clock on any position-1 reply |
| Q41 | **Step 4 screenshot matrix** (2026-11-11, mentor amendments). `npm run screens` (`playwright.screens.config.ts`, `design/render-states.spec.ts`, mock text in `design/screen-fixtures.ts`, the same mocks and production build as the e2e suite; not in `check.ps1`). **Matrix:** states 1, 10, 11 at 390/768/1024/1440 x light/dark; state 15 (the sheet) at 390/768/1023 x light/dark (at 1024+ it is the panel, already in state 1); all other states and variants at 1440 light, 390 light and 1440 dark; 12, 13, 14 also at 768 and 1024 light (1024 is the narrowest side-by-side, so overflow shows there first); states 1 and 14 at 320x568; state 1 at 1920x1080. Extra captures: state 12 scrolled to the middle and the end; state 18 "expanded" (scroll container unclamped; for typography only, not what a visitor sees). **Deterministic:** clock via `install` + `pauseAt` + `runFor` (frozen, so nothing ticks between state and shot; `setFixedTime` also works but keeps real timers running), reduced motion, animations disabled, `document.fonts.ready`. **Mock text** is hand-written in the fixture's voice: the long answer is ~450 words (the realistic maximum at `max_completion_tokens` 600, not 600 words); long lines include one of ~300 characters. **Output:** `frontend/design-review/round-<ROUND>/` (gitignored; never committed; README images are copied deliberately in slice 6), with `manifest.json` (commit, dirty flag, date, shot count), `notes.md` (automatic notes, never assertions: clipped overflow and sideways page scroll, text under 12 px, the reading measure in characters (target 45-75) and line-height, text under the composer's fade), and contact sheets of at most ~1500 px width (at most 6 tiles per sheet for wide shots, 8 for phone widths; the first sheet is read before the rest to check legibility). **Review:** findings as rows (state, width/theme, finding, severity, proposed fix) against the Q29 brief and the checklist; I decide each row; after round 1 the mentor gets a few sheets for an independent look; each round is recorded here | Every state reviewed at the widths where it can break, from the same mocks as the tests, traceable to a commit | `.mjs` script (can't import the TS mocks); 600-word answer; full-page shots for every state; inlined data-URI contact sheets; 24-tile sheets (unreadable when downscaled) |
| Q42 | **Slice 4: the daily token budget** (grilling, 2026-11-11, mentor-reviewed, my decisions). **Finding:** Groq's free tier for `qwen/qwen3.8-27b` is 30 RPM, 1K RPD, 8K TPM, **200K TPD**, per organization (console limits page, checked by me); there is no TPD header and the daily reset is undocumented. At ~3,000 tokens a question that is **~65 questions/day in total**, so Q6's "~500-600/day" (based on RPD) is superseded. **Budget:** counted over a **rolling 24 h** in hourly buckets in the `usage` table. Each answer's real `usage` tokens (prompt + completion, retries included) are added after the answer; if that write fails, the answer is still returned and the undercount logged. A timeout counts ~3.3K **only if a Groq request was started** and its outcome is unknown; a timeout while queued or embedding counts 0. Buckets older than 24 h are pruned (the daily outcome counters are kept). **Admission:** tokens in the window + ~3.5K per question in flight + ~3.5K <= `public_budget_tokens`. **`public_budget_tokens` = 120K** (~37 questions) while I develop, **raised to 170K after slice 5's pre-generation (note 2026-11-12: that generation runs on the dev DB, outside this table, and is finished at least 24 h before launch, Q53)**, always leaving >= 30K. It is stored in the `usage` row, set by a local script that uses the API's own role. Outside use (my tests) is not tracked: I lower the budget by hand on test days. A real TPD 429 from Groq is final until its `retry-after`, and the first one is logged as a finding (the real reset). **No live cache in M2;** only daily outcome counters (accepted, refused by reason, budget hit), never question text | The daily budget, not the request rate, binds; a rolling window is safe whatever Groq's reset is; when the budget is spent the site stays useful (example, slice 5 answers) | Q6's ~500-600 requests/day cap; a fixed UTC day; cross-checking Groq's request headers for outside use; an in-memory answer cache; upgrading to Groq's Developer plan (pay-as-you-go, breaks $0) |
| Q43 | **Slice 4: an /ask deadline** (2026-11-11). Each `/ask` gets **~90 s from arrival** (the proxy allows >= 120 s, measured in slice 0). The deadline is passed into the queue wait (`Limiter.acquire()` gains its missing timeout), the Voyage call and the Groq call, with each HTTP timeout capped at the time left. A Groq 429 or 5xx is retried at most once, and only if time remains; never after a timeout. A Voyage 429 is retried at most once, if time remains. On expiry, slots are released and the existing JSON `timeout` error is returned, so the page needs nothing new. The browser keeps no fetch timeout (the deferred slice 3 item, closed) | A browser timeout wouldn't free the server's thread or stop it spending budget; one server deadline bounds everything | A browser timeout (alone or as well); no bound |
| Q44 | **Slice 4: abuse controls** (2026-11-11). **Per IP:** one question in flight, plus **5 a day over a rolling 24 h**, counted in memory under a salted hash of `CF-Connecting-IP` (**IPv6 keyed by its /64**), entries evicted after 24 h. Only accepted questions count; a question that **fails on our side** (timeout, 5xx, no answer shown) **is refunded** (the token budget still counts what was used). The per-IP number is read from the `usage` row: 5 in prod, higher in the dev database so my own checks aren't capped. Requests without `CF-Connecting-IP` share one "unknown" bucket (Q6b). **Kill switch:** a flag in the same `usage` row, read by the same statement as the budget, flipped by the local script; if the table can't be reached, questions are refused (fail closed). Flipping it refuses new questions at once; questions already accepted finish. **Order of checks in `/ask`:** kill switch -> previous question still in flight -> per-IP daily -> token budget -> queue busy (~60 s estimated wait; queue shorter than the 40-thread pool). Read-only checks come first and counters increase only on acceptance. **Slice 6 gate:** verify `CF-Connecting-IP` from two networks plus one forged header before going public | Per-IP limits protect fairness, the token budget protects the day; a DB flag needs no redeploy (which would also wipe the per-IP counters) | 20/h + 60/day (60 would be the whole budget); an hourly limit; UTC-midnight reset; a kill switch as an environment variable |
| Q45 | **Slice 4: `/status` and the new messages** (2026-11-11). `queue: {position, wait_s}` is **final** (Q40), with Q40's `/status` rules. New optional `service: "ok" \| "paused" \| "daily_limit"` (paused wins) with a relative `retry_after_s` for daily_limit; parsed tolerantly, an unknown value counts as ok. **Messages** (neutral tone, `role="status"`, in `messages.ts`, relative time "about N minutes/hours", never a clock time): daily limit "Live questions are used up for now. Try again in about N hours. This demo runs on a free API tier, so live questions are capped each day. The example answer above still works."; paused "Live questions are paused right now. The example answer above still works." (no reason given, so it stays true); per visitor "You've reached the daily limit of live questions for one visitor. Try again in about N hours. The example answer above still works."; previous question "Your previous question is still being answered. Try again in a moment." (its own code, the busy countdown, `Retry-After` = time left on the deadline). "Example answer" becomes plural with slice 5 | One enum can't contradict itself; the page states what is true without exposing the remaining count | Two booleans; an absolute `eta`; a global `queue_length`; giving a reason for a pause |
| Q46 | **Slice 4 build plan** (2026-11-11, mentor-approved with amendments). **Queue (C1):** in-process FIFO tickets under a `threading.Condition`; only the head may start; exception-safe cleanup (a ticket is always removed and slots released on success, error or timeout); tested as a pure state machine with an injected clock, plus one real-thread smoke test. **Pacer (C2):** the head starts when a Voyage slot is free, Groq's tokens-per-minute allow ~3.5K more (headers from the last response; after `reset-tokens` has passed, or with no headers yet, assume the minute is full minus estimates) and our output tokens in the last 60 s plus **600 reserved per question in flight** stay under ~1,000 (trued up after each answer). **Wait (C3):** `wait_s` = (position - 1) x a moving average of the gap between starts, **starting at 30 s**; busy above 60 s; a test compares the estimate with the simulated wait in the burst. **`/status` without the database (C4):** an in-memory copy of the usage state, refreshed by every `/ask` (which always reads the row, so enforcement never lags) and, single-flight, in the background when older than 30 s; a failed refresh keeps the stale copy; no copy yet = `ok` plus a refresh. Neon is queried at most every 30 s and only while visitors are present. **Schema (C5):** `usage_settings` (one row: `public_budget_tokens`, `per_ip_daily`, `paused`, `blocked_until`), `usage_hourly` (hour, tokens), `usage_daily` (day, outcome, count); **no pruning** (~8,800 hourly rows a year), so Q7 needs no DELETE. **Codes (C6):** `daily_cap` is renamed **`daily_limit`** everywhere; `paused` 503 (JSON body, unlike Render's own 503), `daily_limit` 429, `per_ip_limit` 429, `in_progress` 429, each with a whole-seconds `Retry-After`; an unknown code stays a generic error with its request id. **Page (C7):** Ask stays enabled when `service` isn't ok; one owner per message, so a service line already shown isn't repeated by the `/ask` refusal. **Admin (C8):** `python -m codeask.admin status \| pause \| resume \| budget <n> \| per-ip <n>`; `status` prints budget, tokens in the last 24 h, per-IP number, paused and `blocked_until`, never `DATABASE_URL`; `budget` refuses more than 170K without `--force`. **Also:** the deadline starts at endpoint entry (`time.monotonic()`); a Groq 429 with `retry-after` > ~120 s is treated as a daily block (no TPD body sample exists; the first is logged for a finding); the ~3.3K estimate counts for **any failure after a Groq request was sent** (timeout or error), not only a timeout, since Groq may have spent the tokens either way (step 2 amendment); a Groq 5xx is now retried without a deadline too (CLI, pre-generation), within the existing `GROQ_MAX_RETRIES`, and the limiter refuses at once when the deadline has passed so an expired question never uses up a Voyage window (step 4); `IP_SALT` from the environment, required in prod, never logged; an outcome `no_client_ip` counts uses of the "unknown" bucket; "try again in about N" rounds **up** (5-minute steps under an hour, then whole hours). **Step 5 amendment (queue and pacer, 2026-11-11, mentor-reviewed, my decisions):** `askqueue.py` (`Pacer` pure, `AskQueue` under one `Condition`; not `queue.py`, which would shadow the stdlib). Tickets WAITING -> RUNNING -> LEFT (or WAITING -> LEFT); `join` (atomic: a Ticket or `Busy`), `try_start` (head only, pacer ready), `leave` (idempotent, always notifies; the 600 reserve is trued up to Groq's `completion_tokens`, kept at 600 if Groq was started with no usage back, 0 if Groq was never called), `wait_turn` (the only blocking code). **The candidate's own 600 counts in the output gate** (qwen rejects a request whose `max_completion_tokens` exceeds what's left of the minute, "Request too large"), so **at most one question runs at a time** and the next starts once recent output <= 400; ~1-2 questions/min, far above the ~65/day budget. Output tokens age out after 60 s **+ 3 s skew**. TPM gate: `remaining-tokens` minus 3.5K per start since those headers; after `reset-tokens` (stored on our monotonic clock at receipt), or with missing/unparseable headers (`ms`/`s`/`m`/`h` parsed; anything else = missing, never raises), the limit (`x-ratelimit-limit-tokens`, else 8K) minus 3.5K per running question; Groq's refill within the minute is ignored (conservative). Only chat responses update the pacer, never the model check. Voyage gate: a read-only `Limiter.ready_at()` peek (safe with one running question and no ingestion in the API process). Groq's `RateLimited` carries its headers so a 429 updates the pacer. **Position:** running = 1, waiting = index + 2 (a head held only by the pacer is "2nd in line"). **Gap EMA** (alpha 0.3, seed 30 s, **clamped to [10, 90] s**) learns from a start only if **the line was non-empty (waiting or running) when that ticket joined** (corrected from "joined before the previous start", which ignored a ticket that joined while another ran). Newcomer estimate 0 on an empty line, else (waiting + 1) x gap; busy above 60 s or at `QUEUE_MAX_TICKETS` = 10, `Retry-After = ceil(gap)`. **`MIN_TIME_TO_START_S` = 25:** a head with less time left raises `DeadlineExceeded` without starting (0 tokens, refunded). `wait_turn` waits at most 5 s at a time (missed-wakeup net, never a zero or negative timeout). Lock order: the queue's lock may take the limiter's, never the reverse. **Burst test, pre-registered before any data:** a fake Groq enforcing the real limits (Request too large, 8K TPM, headers); 12 arrivals within ~20 s; 200 seeds; two output distributions reported separately (realistic: mean ~334, max 460; worst: every answer 460). Hard invariants in 100% of seeds: no exception escapes, **zero fake-Groq rejections**, FIFO starts, at most one running, every ticket ends LEFT, a `Busy` `Retry-After` is truthful. Of admitted tickets, **at most 5% may end in `DeadlineExceeded`** (realistic distribution). Estimate tolerance `|estimate - actual| <= max(gap, 50% of actual)`; on failure fix the estimator, never the tolerance. **Escalation if it fails (stop at the first that fixes it):** (1) a gate-aware estimate from the real output stamps and an EMA of output tokens (seed ~400), admitting only if the estimated start plus the floor fits before the deadline (turns a late timeout into an immediate busy); (2) the floor from the measured p95 service time plus a margin; (3) `max_completion_tokens` 600 -> 500 (needs an answer-quality check and my decision); (4) the deadline to at most 100 s (a Q43 change, my decision). A `DeadlineExceeded` before start costs nothing (0 tokens, refunded); the harm is UX. Reported back: failing seeds per distribution, estimate-error distribution, longest wait before a start, fake-Groq rejections. **Step 5 amendment 2 (escalation 1, 2026-11-11, mentor-reviewed, my decisions). The measured failure:** the average-gap estimator FAILED its pre-registered criteria. 200 seeds: timeouts 30.9% of admitted (realistic) and 61.2% (worst, every answer 460) against the 5% limit; an untruthful `Retry-After` in 195/200 and 200/200 seeds, and **also on clean retries** (1,027 of 1,072 and 1,800 of 1,800 refused with nobody joining in between, so my guess that only other visitors caused it was wrong); 10/533 and 14/233 starts outside the tolerance; the longest wait 65 s = 90 - 25 (the floor cut every longer one). The pacer itself passed: 0 fake-Groq rejections, FIFO, at most one running, nothing stuck. Cause: the gap between starts is bimodal (~3-15 s after an answer of <= 400 output tokens, ~63 s once recent output is > 400), so its mean is too low exactly in the costly case. **Q46 C3's `(position - 1) x gap` is superseded** by a projection: `AskQueue._projection(now)` runs the real `Pacer.next_start` forward on a copy of all pacer state (output stamps, running count, headers, starts since the headers, so each projected start also deducts its 3.5K), every unfinished answer assumed to take `S` seconds and `X` output tokens. **`X` = the max of the last 20 answered outputs, clamped to [460 seed, 600]; `S` = the max of the last 20 answered service times, seed 15 s, clamped to [5, 60] s** (high values, not means: the output gate is a threshold at 400, and a mean of ~334 says "starts at once" exactly when the 63 s case can still happen). A running answer already past `S` is assumed to need 5 s more. Voyage bounds only the first projected start (later projected starts are ~63 s apart, so they can't fill a 65 s window of 3). `wait_s` = projected start - now (the Q40 shape is unchanged). Busy if the newcomer's projected wait is not `<= 60` or at `QUEUE_MAX_TICKETS`; `Retry-After = max(1, ceil(projected start - now - 60) + 1)`. The gap average, its clamps and `START_GAP_*` are removed. **Plain consequence:** since `X` >= 460 > 400, the projection treats every running answer as blocking the next start, so a second visitor arriving early in a run gets busy with a short `Retry-After`; measured, not assumed, in two- and three-visitor scenarios (2 arrivals within 5 s, 3 within 10 s). If that busy rate is a UX problem, escalation 3 (`max_completion_tokens` 500) is reconsidered, my decision. **The criteria changed because the design changed, fixed before the new run:** the old two-sided "1 gap" tolerance fitted a mean-type estimator; over-estimates are now intentional. New: **hard, 100% of seeds where the assumptions hold** (outputs <= `X`, service <= `S`): `actual start <= projected start + 2 s` for every started ticket, plus an oracle test (every output = `X`, every service = `S`: actual = projected within 1 s); **realistic distribution, live seeds:** >= 99% of started tickets have `actual <= estimate + 2 s`; timeouts <= 5% of admitted (target ~0%); `Retry-After` is a hard invariant for clean retries only (contested ones reported); reported, not asserted: over-estimates (median, p95), the busy share, the old two-sided number with 30 s in place of the gap. Escalations 2-4 stay unused if this passes, except that the floor and the `S` seed come from the live p95 service time before slice 6 (its Done-when). "2nd in line" will rarely be exceeded: accepted (correctness over queue theatre). Rejected: the mean output (seed ~400) as `X`; keeping the average gap. **Step 5 amendment 3 (2026-11-11, mentor-reviewed, my decisions). Escalation 1's first run:** it passed everything except one rule. 0 fake-Groq rejections, FIFO, one running and nothing stuck in all four distributions; **0 timeouts** (realistic 0 of 443 admitted, worst 0 of 376); 0 starts later than the estimate + 2 s; the oracle and upper-bound property tests passed in every seed; over-estimates median 0.0 s, max 1.0 s; busy 82% (realistic) of a 12-in-20-s burst. **It failed the clean `Retry-After` rule:** 58 seeds realistic (194 of 800 clean retries refused), 76 worst (332 of 970), 0 in oracle and bounded. Diagnosis (predicted in writing before the run): bounded and realistic share the output distribution and differ only in service time (3-5 s vs 3-15 s), so service exceeding `S` caused it. The [5, 60] clamp let `S` fall below its seed to the longest time seen so far, a later answer ran past it, the 5 s overdue margin moved the newcomer's start, and an on-time retry was refused again. (For the record, my earlier diagnosis of the old estimator's `Retry-After` failure, "other visitors joining", was wrong, see amendment 2; this one is verified by a counter of refused clean retries with an answer running past `S`.) **Fix, in the estimator, not the criterion: `S` is clamped to [seed, 60]**, like `X` (a few fast answers say little about the slowest); `PROJECTED_SERVICE_MIN_S` is removed. The guarantee in production rests on the seed being a real upper bound (slice 6 Done-when: the longest measured service time plus a margin). **Added to the report:** a "slow tail" distribution (10% of services 20-40 s, above the seed; informational, but no exceptions, stuck tickets or fake-Groq rejections allowed), and a "false busy" count (the same visitors with nobody refused: how many refused ones would have started in time; informational, no threshold, overstated since admitting them delays others). **Escalation 3 (`max_completion_tokens` 500): not now.** Measured: of 2 visitors within 5 s, the second was admitted in 1 of 200 seeds (busy, `Retry-After` median 18 s). The deciding case is one visitor's follow-up question, **pre-registered:** asked 30 s after the first answer finished (realistic, 200 seeds), >= 80% start within 2 s and none is refused as busy; reported also at 20 s and 45 s. If it fails, escalation 3 returns as a candidate, my decision. **Results after the fix (200 seeds each; the predictions were written before the run and all held):** 0 clean `Retry-After` refusals in realistic (0 of 690), worst (0 of 1,020), oracle and bounded; 0 timeouts; 0 starts later than the estimate + 2 s; 0 fake-Groq rejections; busy 81% (realistic) and 84% (worst) of a 12-in-20-s burst. Slow tail: safety held (0 rejections, nothing stuck, FIFO, 0 timeouts); 266 of 918 clean retries refused, **261 of them with an answer running past `S`** (the diagnosis confirmed; the other 5 are not explained by this counter, my unverified guess is a slow answer's tokens stamped late); 5 started answers would run past their deadline. **Follow-up question (pre-registered rule passed):** at 30 s, 170 of 200 (85%) started within 2 s and 0 were busy; p95 wait 43 s at 20 s, 33 s at 30 s, 18 s at 45 s. So escalation 3 stays unused. False busy: 342 of 1,952 refused (18%, realistic) and 194 of 2,022 (10%, worst) would have started in time with nobody refused, the price of an upper bound. **Decided for step 8 (2026-11-11, my decision: yes):** the queued sentence becomes "Next in line, up to about N seconds." for position 2 and "3rd in line, up to about N seconds" from 3 on (an exact-text change in `messages.ts` and its tests), because a lone visitor held only by the rate limit isn't "2nd in line" and `wait_s` is now an upper bound. **Step 6 decisions (wiring `/ask` and `/status`, 2026-11-11, mentor-reviewed, my decisions):** (1) **one database session for the whole `/ask`, queue wait included**, on the condition that no transaction is open while waiting: `connect()` is autocommit and every `Store` method is one `with conn.transaction()` block, so a `db` test asserts the connection is IDLE after the reads; nothing uses session-level state on the pooled endpoint (no `SET` outside `UPDATE`, no advisory locks or temp tables, `search_path` already avoided). Fallback if that ever breaks: open the session after `wait_turn`. (2) **Refunds:** an ungrounded answer is a real, shown result and is **not** refunded (a refund would also let one IP burn tokens on ungrounded questions); refunded, as an explicit list in code: timeout, any 5xx (upstream, database, internal), Voyage failure, model gone, busy after acceptance, and a Groq daily-limit 429 after acceptance. (3) **C6's "each with a whole-seconds `Retry-After`" means the three 429s** (`daily_limit`, `per_ip_limit`, `in_progress`); `paused` has none (nobody knows when it ends). (4) **`IP_SALT` is required at startup with real dependencies,** at least 16 characters, the error names the variable and never its value; tests pass a salt directly; rotating it only resets the in-memory counters, so it is safe. (5) **The `daily_cap` -> `daily_limit` rename is entirely frontend (step 8)**; until then the page shows the generic error with the request id for `daily_limit` (checked: `api.ts` maps unknown codes to `error` and keeps the request id). **Step 7 amendment (the admin script, 2026-11-11, my decision):** `setup()` is an explicit **`python -m codeask.admin setup`**, run once per database by a role that may create tables (the dev database now, the prod owner role in slice 6), not run before every command: Q42 has the script use the API's own role in prod, which can't create tables (Q7), and Postgres checks the CREATE permission even for `CREATE TABLE IF NOT EXISTS`. The other commands only read the usage row and update `usage_settings`, so they work with the API role. Each change prints its before and after values; a database error prints only its type name (psycopg messages name the host and user). No "unblock" command: `blocked_until` expires on its own and reflects Groq's own daily limit. **Step 8 decisions (frontend, 2026-11-11, mentor-reviewed, my decisions):** (1) **the example sentence is true or absent:** each Q45 message is its text without the example tail, plus "The example answer above still works." only when an example is actually on screen (a boolean into `messages.ts`, never a repo name): on load for a repo with an example, never in an `/ask` refusal (the asked question replaces the example; the "Show the example answer" button does that job). (2) **The service line lives in the composer's status slot**; a connection message (waking, down, offline) wins, since the page can't know the service then. (3) **One owner per message:** the composer line is quiet only while the question's own status shows a refusal whose code equals the current `service` value; a refusal that changes the value makes the line follow it, then go quiet; after "Show the example answer" the line reappears (derived from state). Tested: never both, never neither, both transitions, and no stale `paused` line after a pause is lifted. (4) **After a `paused` or `daily_limit` refusal the asked question stays as the heading** with the calm message, no retry, and "Show the example answer" when there is one. **`service`** comes from every `/status` reply the page already makes and from `/ask` (a `paused`/`daily_limit` refusal sets it, an answer sets `ok`); **no polling while idle**, but **one `/status` fetch on `visibilitychange` to visible, only when `service` isn't ok and the last fetch is over 60 s old** (visitor-initiated, like a reload, so Q14 holds). The "about N" text is static (a countdown would chatter in a live region). **`in_progress`** reuses the busy countdown with its own calm sentence (the visitor's earlier answer, from before a reload, is abandoned and can't be shown again). **"About N" (amends Q46's "rounds up"):** under an hour, up to the next 5 minutes; **from an hour on, to the nearest hour, at least "about 1 hour"** (61 min overstated by ~100% when rounded up; an early retry costs nothing, a refused retry isn't counted and shows a fresh time). **Contract drift test:** the backend tests write the real refusal and `/status` bodies (with `Retry-After` and the exposed-headers list) to a JSON file the frontend logic tests run `classify()` and `readService()` over; a pytest asserts the file is current. **Layout, pre-registered:** with the longest message (daily limit), the sticky composer stays at or below 40% of the viewport height at 390x844, and the ask box is fully in view at 390x844 and 320x568 (e2e); if that fails, the composer slot keeps the first sentence plus the time and the rest moves into the scrolling column as a calm paragraph. **Step 9 adds a real-browser check** with the real backend and dev database: pause via the admin script (service line on load, refusal with one owner), resume; a low per-IP limit to trigger `per_ip_limit` (the real `Retry-After` read through CORS); `daily_limit` only if it can be triggered safely; observations listed, not asserted blind. **Order:** schema -> budget -> per-IP -> deadline -> queue and pacer (burst test) -> `/ask` and `/status` -> admin -> frontend (`service` parsing, four messages, `in_progress` reusing the busy countdown, rename, e2e and axe in both themes, screenshot states) -> `check.ps1` and one live question | Smallest design that meets Q42-Q45; the deadline exists before the queue that waits on it | asyncio queue; a 30 s timer refresh (keeps Neon awake, R6); pruning with a DELETE grant; keeping `daily_cap`; disabling Ask on load |

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
| Q47 | **Slice 5: where answers live** (grilling, 2026-11-12, mentor-reviewed). Generated and reviewed on the **dev DB**, shipped to prod unchanged; prod's re-ingest at the same pinned SHA keeps them valid (amends slice 6's "generate their answers in prod"). **No table:** committed JSON files are the store, one per answer in `frontend/data/examples/<owner>__<name>/`, plus a per-repo `index.json` for the order; failed attempts go to `eval/results/`. Each repo's set is a dynamic import; `check.ps1` validates the shapes offline. Every JSON records the generation settings as the fixture does (model, prompt version, temperature, reasoning setting, `max_completion_tokens`, packer settings, usage) and every `generated_at` and note uses one format: ISO 8601 in UTC with the offset stated (`2026-11-12T10:00:00+00:00`) | Temperature 0 isn't reproducible (Q37), so reviewed answers must be stored and reused; the files are already the shipped form, so a table would only add an export hop | A dev table + export script (the slice 5 text); regenerating in prod |
| Q48 | **Slice 5: questions, frozen.** I write 5-8 questions per repo (no LLM-written questions, Q13). **Amended 2026-11-12:** the questions were proposed by the mentor chat (Claude) from general knowledge of the three libraries, before any generated answer existed; I selected them and accept them as mine. Two reserves per repo, used in order for replacements, belong to the same pre-registered set. Files: `eval/m2d_questions/<owner>__<name>.json` (questions in index order, reserves, expected chunks). Before freezing, Claude checked each against the clone at the pinned SHA: all 18 questions and 6 reserves are answerable from the repo's own code, so no substitution was needed. Claude drafts expected chunks from a clone at the pinned SHA (the same commit as `featured.json`), I confirm them, and both are committed **before the packer comparison and before generation**. After anyone has seen a generated answer, neither is edited: rewording a question counts as a replacement (a failed attempt plus a new question). **Flagship** = the first passing entry in the index (I may reorder after review), and it must also be graded `correct` in the rubric's "correct" column with **no omission flagged as material** (a slight omission is allowed if the mechanism is fully explained; reworded 2026-11-12, mentor; the itsdangerous fixture qualifies with its grade note unchanged, and the same definition applies to every repo's flagship), have >= 3 valid citations and not be truncated; if no passing answer qualifies, the first passing entry is used and the reason recorded. itsdangerous keeps the key-rotation fixture unchanged as one of its set (and its flagship, subject to the open point under slice 5). **Pre-freeze notes (2026-11-12, mentor):** all questions are kept as listed. The requests q1 `required` set is what a complete answer needs (5 functions, about 350 lines), more than the 2,000-token budget can pack, so the answer is expected to be incomplete and may fail the flagship rule; I may reorder after review; the budget doesn't change (tuning is M3). The expected-chunk coverage rule is the m2 comparison's (`eval/m2_pack_compare.py`): a range counts as packed only when every non-blank line of it is inside the packed blocks; a partial overlap doesn't count. **Confirmed and frozen 2026-11-12:** I spot-checked itsdangerous q1, requests q2 and q5, and express q2 and q3 against the files at the pinned SHAs; the mentor reviewed the table's structure and consistency, not the line numbers. The set is committed before the Q49 comparison and before any generation. | The question set can't be tuned to the answers; the flagship is what a recruiter sees first | Claude proposing questions; questions without expected chunks |
| Q49 | **Slice 5: the Q28 packer re-run, before any generation**, retrieval only, on every question of the three repos, against the confirmed expected chunks. **Rule, fixed before running:** keep no cap / 2,000 unless a capped variant packs strictly more of the expected chunks on **both** requests and express **and** loses none on itsdangerous; ties keep the default; only coverage decides. **Result 2026-11-12: kept.** Required chunks packed at 2,000 were tied across all four variants on requests (9/19) and on express (16/21); on itsdangerous, no cap and cap 5 packed 10/11. The table is under build step 3 | Packer settings shape every stored answer, so they are settled first; one repo was the only evidence for Q28 | Generating first and recording the comparison for M3 |
| Q50 | **Slice 5: review outcomes.** **Pass** = grounded, every citation valid, no incorrect claim ("correct but incomplete" passes). A failure is recorded as an eval finding and the question is replaced; **no re-rolls**, except runs that ended in an error with no answer text (Groq 429/5xx, Voyage 429, timeout, DB): at most 2 re-runs per question, each logged. A cutoff (`finish_reason: length`) is graded as it is; a visibly truncated answer fails as an attempt. At most 3 replacements per repo. **Stop rule:** N = the repo's initial question count; generation stops when its failures exceed N / 2 (for N = 6, the 4th failure); replacements count as attempts and never change N. **After a stop**, the cause is classified here before anything is regenerated: a **bug** (behaviour contradicting the documented design) is fixed, passed answers are kept and only the stopped repo restarts; **tuning** (budget, cap, K, prompt wording) is deferred to M3 and the stopped repo ships what passed (fewer than 5 if so, with the count recorded). After any chunker, packer or prompt code change, the cited-lines check (Q51) is re-run on every stored answer and failures are regenerated. Counts per repo are reported. **Amended 2026-11-12 (mentor), before generation: unsupported claims.** A claim the cited blocks don't support is flagged `unsupported`, even if it is true. An answer fails if any claim is incorrect, or if an unsupported claim is load-bearing (part of the main answer). A minor unsupported background claim is flagged but allowed | Failures are retrieval evidence for M3, not noise to re-roll away; a fixed denominator keeps the stop rule from drifting | Re-rolling until it passes; rephrasing after seeing an answer; retuning mid-slice |
| Q51 | **Slice 5: grading and the cited-lines check.** Claude drafts claim-by-claim grades against the blocks and marks the 2-3 riskiest claims, as `reviewer: "claude"`; I spot-check and flip to `author`; unflipped answers ship with the Claude label (Q37). **Cited-lines check:** a fresh clone at the pinned SHA, each block's lines compared exactly with the file's lines, the result recorded in the JSON; `check.ps1` runs only offline structural checks. **Grade shape (confirmed 2026-11-12):** `correct` is `correct`/`incomplete`/`incorrect`; `grounded` is `yes`/`no`; `citations_valid` is descriptive; `unsupported` is `none`/`minor`/`load-bearing`; `omission` is `none`/`minor`/`material`; `claims` lists `{claim, verdict, blocks}` with the 2-3 riskiest marked; then `reviewer`, `date`, `note`. **Pass and flagship are computed, never stored** (no field can contradict another, Q37). Pass = `grounded` is yes, `correct` isn't incorrect, `unsupported` isn't load-bearing, every citation is valid and `lines_check.ok`. Flagship = the first passing answer in question order with `correct`, no material omission, >= 3 valid citations and not truncated (`completion_tokens` at the 600 cap); otherwise the first passing answer, with the reason in `index.json`. itsdangerous q1 gained `unsupported: "none"` and `omission: "minor"`, read from its recorded note; nothing else in it changed | The blocks came from the dev DB, so only the real files at the SHA are an independent check; the label stays honest about who checked | I grade all from the start; checking against the DB; GitHub raw files |
| Q52 | **Slice 5: the SHA guard** (amends Q13). A pinned `commit_sha` per repo in the static featured list, with a test that every shipped answer matches it; the export refuses an answer whose SHA differs from the dev DB (a second guard); a drift guard (pytest, fails loudly) compares slug **and SHA** of the static list with the backend's `FEATURED_REPOS`, which gains the pinned SHA per repo (mentor, 2026-11-12); ingesting a featured repo without an explicit ref defaults to that SHA. Slice 6 checks `/repos` against the pins after the prod ingest. **No runtime check** against `/repos` | The page must work with the backend down; a pin checked in tests and at export can't drift silently | Hiding answers at runtime when `/repos` disagrees |
| Q53 | **Slice 5: tokens and pacing** (amends Q13's "generation counts against the daily cap"). The CLI calls Groq directly, outside the live budget table: it records real usage in each JSON, prints a running total and has a `--max-tokens` guard (100K per run; failed runs count). I lower the live budget by hand on generation days; generation is finished at least 24 h before launch. The CLI **paces itself** (the existing `Pacer`: Groq headers plus its own output tokens, about two questions a minute) and applies the same 90 s deadline per question, so rate limits don't masquerade as infrastructure failures | The live table guards visitors; a run of ~20 questions is mine, planned for a quiet day | Writing CLI usage into `usage_hourly`; no pacing |
| Q54 | **Slice 5: the page** (amends Q8). Each repo opens on its flagship; the other questions are a list below the answer in the scrolling column, also under live answers, hidden while a question loads. A click shows the stored answer at once: the item stays in the list with `aria-current`, focus moves to the new heading, scrolled into view (instant under reduced motion), and the composer draft is kept. Typed questions always go live, even when they match a suggestion; the placeholder is unchanged. **Label:** today's "Example answer, generated <date> with <model> on commit <sha7>." plus the Q37 check sentence, for every stored answer. **Copy:** "The suggested questions still work." (no direction word) replaces "the example answer above" in the Q45 messages and `EXAMPLE_STILL_WORKS`, shown only when the list is on screen. **Q8 amended:** the list replaces the follow-up chips (never built); only the "each question is answered on its own" note is built, under live answers | One stored answer on screen keeps the first screen calm; a typed match served from storage would blur what is live | Suggestions only in the empty state; serving typed matches; follow-up chips as well |
| Q55 | **Slice 5: verification and attribution.** One `round-s5` screenshot round on the new states (Q41 matrix); axe in both themes and forced colors; e2e for the keyboard, focus and scroll flow and for "pre-generated answers with the backend down"; the review-skill passes stay in slice 6. **Licence line** in the README's "How it works": the code excerpts belong to their authors, shown under their open-source licences, each named from its LICENSE file at the pinned SHA. Out of scope: `?repo=` and CodeAsk as a featured repo (slice 6) | Same depth as slice 4's new states; the site shows other people's code in public | Axe only; more rounds; assuming the licences |

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
- **Cost per question is a measured axis (from slice 4, Q42):** Groq's 200K tokens/day for
  qwen allows ~65 questions/day, so the 2,000-token context budget (Q28) and the ~700-token
  prompt overhead are revisited here, against retrieval and answer quality, not before. Groq's
  daily limit is **per model** (gpt-oss-20b and gpt-oss-120b each have their own 200K): another
  already-compared model adds capacity only if its validity meets the slice 1 threshold.

**Done when:** one command runs retrieval over the ~30-question set on the pinned repo and prints
hit rate@k and MRR. The baseline numbers are recorded in this file.

## [ ] M4 Agent mode
Tools `search_code`, `read_file`, `list_dir`; LLM loops until it can answer.
**Budget constraint (from slice 4, Q42):** agent mode makes several LLM calls per question, so it
can't run live under qwen's 200K tokens/day unless its public demo is pre-generated, or it uses
a separate model with its own daily budget.

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
