# CodeAsk

Chat with a GitHub codebase: ask a question, get an answer that cites real files and line
numbers. A portfolio project built on free tiers only.

The web app answers questions about a few pre-indexed **featured repos** only. To use your own
repo, run the ingestion locally (any `https://github.com/<owner>/<repo>` URL); the app has no
ingestion endpoint.

## Status

Work in progress, **not deployed yet**. Milestones, design decisions and measurements are in
[PLAN.md](PLAN.md).

- **M0 spike:** done. Free-tier limits measured, stack confirmed.
- **M1 ingestion:** done. Clone, filter, chunk by syntax (tree-sitter for Python,
  JavaScript and TypeScript; heading-based sections for Markdown and reST; line windows
  otherwise), embed with Voyage `voyage-code-3`, store in Neon Postgres + pgvector.
- **M2 basic RAG chat:** built and tested locally; deployment is in progress. A FastAPI
  backend retrieves the closest code, has a Groq-hosted model answer with citations, and checks
  every cited line range on the server against the code the model was given; a bounded queue,
  per-visitor and daily limits and a pause switch keep it within free tiers. A Next.js frontend
  shows the cited code beside the answer, and suggested questions with stored answers that work
  even when the backend is asleep. Tested with qwen3.8-27b (Groq Preview) as of Nov 2026.
- **Next:** deploy M2, then M3, an evaluation harness for retrieval (hit rate, MRR).

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

## Privacy

<!-- privacy:start (kept equal to PRIVACY.summary in frontend/lib/messages.ts by a test) -->
Questions you type are sent to Groq (to write the answer) and Voyage (to find the code). Groq
is set not to store them; Voyage may keep them and use them to train its models, so please don’t
enter personal information. CodeAsk’s own server stores no question text and no IP addresses,
only usage counters. Its hosts, Render and Vercel, keep standard request logs, which include IP
addresses, for their own retention periods. Suggested questions are answered from files shipped
with the page and are not sent to Groq or Voyage.
<!-- privacy:end -->

## Licence

CodeAsk's own code is MIT-licensed ([LICENSE](LICENSE)). Third-party code it depends on or
reproduces is listed, with licence texts, in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
and [third_party/licenses/](third_party/licenses/). The featured repos' code shown on the site
keeps its own licences (see [Code shown on the site](#code-shown-on-the-site)), and the
development skills are credited below.

## Development skills

CodeAsk was built with Claude Code and a few agent skills. They are not part of this repo
(`.claude/skills/` is gitignored); install them yourself to reproduce the workflow.

- `frontend-design`, `karpathy-guidelines`, `vercel-react-best-practices` and
  `web-design-guidelines`: listed with their sources in `skills-lock.json`.
- `grill-me` and `grilling`: **Matt Pocock's skills, used unmodified**, from
  [mattpocock/skills](https://github.com/mattpocock/skills) (MIT, Copyright (c) 2026 Matt
  Pocock), `skills/productivity/grill-me` and `skills/productivity/grilling` at commit
  [`5863806`](https://github.com/mattpocock/skills/tree/5863806dd4e15c63174bee4e7515a4256792ecfa/skills/productivity)
  (the local `SKILL.md` files are byte-identical to that commit). They are not in
  `skills-lock.json`. Install with the `skills` CLI:
  `npx skills@latest add mattpocock/skills --skill grill-me --skill grilling -a claude-code`

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

## Releases

Deploys come only from the `release` branch, which is moved by hand to a commit that has passed
every check (`scripts/check.ps1`, `pytest -m db`, gitleaks):

```bash
git push origin <sha>:release
```

Vercel builds only `release`; Render has auto-deploy off and is deployed by hand from the same
commit. Once a commit is pinned, only documentation changes go to `main` until that release
is deployed and checked; a code change means a new pin and the checks again.

## Tests

```bash
pytest            # unit tests, offline (~2 s)
pytest -m db      # integration tests on a throwaway Neon schema (fake embedder, no quota)
pytest -m slow    # the real Voyage tokenizer (local, no API requests)
```
