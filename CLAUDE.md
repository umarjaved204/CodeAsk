# CodeAsk

Paste a GitHub repo URL and chat with that codebase. Answers cite real files and line numbers.
Includes a RAG evaluation harness (hit rate, MRR), and later an agent mode and voice input.
Portfolio project. Milestones and status live in [PLAN.md](PLAN.md).

## Working style (follow every session)
- **I run all terminal commands myself.** Give each command as a copy-paste block for
  **Windows 11 PowerShell 5.1**, with a one-line explanation, then wait for me to say it's done.
  Do not run commands yourself unless I explicitly ask.
- You may create and edit files directly.
- Plan before coding. Explain trade-offs briefly and recommend one option.
- I want to understand RAG deeply: explain the *why* behind design choices
  (chunking, embeddings, retrieval, evaluation) as we go.
- Keep scope tight. No over-engineering, no features I didn't ask for.
- Commit and push at the end of every work session (I once lost a whole project).

## Hard constraints
- **$0 budget except the domain name.** Hosting, APIs and database must be free,
  ideally with no credit card on file. Flag anything that would need a card or could bill.
- Secrets go in `.env` only (gitignored). Never hardcode keys or commit them.
  Keep a `.env.example` with key names and no values.
- A secret-scan pre-commit hook lives in `.githooks/`. After any fresh clone, enable it with
  `git config core.hooksPath .githooks`.

## Planned stack (verify free-tier limits in M0 before relying on them)
| Layer | Choice | Notes |
|---|---|---|
| Frontend | Next.js on Vercel Hobby | |
| Backend | FastAPI on Render free | Free instances sleep when idle, so expect cold starts |
| Database | Neon Postgres + pgvector | |
| Embeddings | Voyage | Rerank only as an experiment |
| Live LLM | Groq | Answers and tool calling |
| Eval LLM | Gemini free tier | Offline evaluation only, never in the live app |

Record measured limits and cold-start behaviour in the "M0 results" section of PLAN.md.
