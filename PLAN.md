# CodeAsk Plan

Status key: [ ] not started · [~] in progress · [x] done

## [ ] M0 Spike
One throwaway script: embed a small repo with Voyage → store in Neon pgvector → retrieve
chunks → answer with Groq, including one tool call. No UI.
Goal: prove every free tier works without a credit card; record rate limits and cold starts.

**Done when:** one script run prints a Groq answer grounded in chunks retrieved from Neon,
Groq made at least one tool call, and the "M0 results" section below is filled in.

## [ ] M1 Ingestion
Clone a GitHub repo, chunk the code (by function/class where possible), embed, store.

**Done when:** given a public repo URL, one command clones it, chunks it, embeds it and stores
it in Neon. Every chunk has its file path and start/end line numbers, and re-running on the
same repo doesn't create duplicates.

## [ ] M2 Basic RAG chat
Next.js chat UI + FastAPI endpoint; answers cite files and lines.

**Done when:** locally, I can paste a repo URL, ask a question in the browser, and get an
answer whose citations (file + line range) point to the correct code.

## [ ] M3 Eval harness
Question set with expected files; hit rate and MRR baseline.

**Done when:** one command runs retrieval over a fixed question set (with known correct files)
and prints hit rate@k and MRR. The baseline numbers are recorded in this file.

## [ ] M4 Agent mode
Tools `search_code`, `read_file`, `list_dir`; LLM loops until it can answer.

**Done when:** agent mode works in the UI, and the eval harness reports agent vs plain RAG
side by side on the same question set, with the results recorded here.

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
| Render (cold start) | | | |

Notes:
