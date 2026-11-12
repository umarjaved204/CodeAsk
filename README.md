# CodeAsk

Chat with a GitHub codebase: ask a question, get an answer that cites real files and line
numbers. A portfolio project built on free tiers only.

The public demo serves a few pre-indexed **featured repos**. To use your own repo, run the
ingestion locally (any `https://github.com/<owner>/<repo>` URL); there is no ingestion endpoint
on the internet.

## Status

Work in progress. What exists today is the **ingestion pipeline** (milestone M1) and a
command-line retrieval check. There is no chat, LLM answer or web UI yet. Milestones, design
decisions and measurements are in [PLAN.md](PLAN.md).

- **M0 spike:** done. Free-tier limits measured, stack confirmed.
- **M1 ingestion:** done. Clone, filter, chunk by syntax (tree-sitter for Python,
  JavaScript and TypeScript; heading-based sections for Markdown and reST; line windows
  otherwise), embed with Voyage `voyage-code-3`, store in Neon Postgres + pgvector.
- **Next, M2:** a basic RAG chat (FastAPI + Next.js) with file and line citations.
  Tested with qwen3.8-27b (Groq Preview) as of Nov 2026.

## How it works

### Code shown on the site

The code excerpts and answers on the site quote the featured repos at a pinned commit. That
code belongs to its authors and is shown under each project's open-source licence, named here
from its licence file at that commit:

| Repo | Commit | Licence |
|---|---|---|
| [pallets/itsdangerous](https://github.com/pallets/itsdangerous) | `672971d` | BSD 3-Clause ([LICENSE.txt](https://github.com/pallets/itsdangerous/blob/672971d66a2ef9f85151e53283113f33d642dabd/LICENSE.txt)) |
| [psf/requests](https://github.com/psf/requests) | `3c7baaa` | Apache License 2.0 ([LICENSE](https://github.com/psf/requests/blob/3c7baaa05ab4aa49cc819ce3a819d260de19c157/LICENSE)) |
| [expressjs/express](https://github.com/expressjs/express) | `1c6f1b0` | MIT ([LICENSE](https://github.com/expressjs/express/blob/1c6f1b0fe4000977b9a7b4f34097e4d527dd9824/LICENSE)) |

## Setup

Requires Python 3.12+ and free accounts for Neon and Voyage AI (no card needed).

```bash
python -m venv .venv
# activate it (Windows: .venv\Scripts\activate), then:
pip install -r requirements-dev.txt
pip install -e .
git config core.hooksPath .githooks   # secret-scan pre-commit hook
```

Copy `.env.example` to `.env` and fill in `DATABASE_URL` and `VOYAGE_API_KEY`.
`.env` is gitignored; never commit keys.

## Usage

```bash
# What an ingest would embed (local tokenizer, no API calls)
python -m codeask.count repos/<owner>__<name> [--tests] [--docs]

# Clone, chunk, embed what isn't cached, and store. Shows the cost and asks first.
python -m codeask.ingest https://github.com/pallets/itsdangerous [--ref <sha>] [--tests] [--docs] [--yes]

# Top 5 chunks for a question (retrieval only, no LLM)
python -m codeask.search pallets/itsdangerous "How is the signing key derived?"
python -m codeask.search pallets/itsdangerous --sanity eval/sanity/itsdangerous.json

# Delete embeddings no chunk uses (kept by default so switching chunking variants is free)
python -m codeask.gc [--all | --delete-repo owner/name]
```

Voyage's free tier allows 3 requests per minute, so a ~60K-token repo takes about 7 minutes to
embed the first time. Re-running is nearly free: embeddings are cached by content, so only
changed code is embedded again.

## Tests

```bash
pytest            # unit tests, offline (~2 s)
pytest -m db      # integration tests on a throwaway Neon schema (fake embedder, no quota)
pytest -m slow    # the real Voyage tokenizer (local, no API requests)
```
