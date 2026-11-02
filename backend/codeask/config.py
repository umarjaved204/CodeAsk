"""Tunable settings in one place. Most are starting guesses that the M3 eval will tune."""

# ---------- File filters ----------
MAX_FILE_BYTES = 100_000
# Data-like / minified code. TableTalk's longest real line is 196 chars. At ~2 chars/token
# (symbol-heavy code) 1,500 chars is ~750 tokens, just under the chunk cap.
MAX_LINE_CHARS = 1_500
MAX_AVG_LINE_CHARS = 200
# Generated-file markers are only looked for in the first few lines.
MARKER_LINES = 5

# ---------- Voyage (no-card limits: 3 requests and 10K tokens per minute) ----------
EMBED_MODEL = "voyage-code-3"
EMBED_DIM = 1024
VOYAGE_REQUESTS_PER_WINDOW = 3
VOYAGE_WINDOW_SECONDS = 65  # 60 s + 5 s margin: M0's 4th request 429'd at ~60 s
# Typical request time. A slot frees one window after the request COMPLETES, so each window
# really lasts window + latency. Fitted to M1: 13 requests took 293 s, 21 took 448 s.
VOYAGE_REQUEST_LATENCY_S = 8
BATCH_TOKENS = 3_000  # M0: 9K-token requests were never accepted; 3K worked
VOYAGE_MAX_RETRIES = 3  # per request, on 429 only; each retry waits one full window
RESERVED_FOR_QUERIES = 0  # slots per window ingestion may not use (set to 1 when the app runs)

# ---------- Chunker ----------
# "ast" = tree-sitter where we have a grammar; "windows" = token-packed line windows for every
# file (the M3 naive baseline, with everything else held equal).
CHUNKER = "ast"
# Token budgets (Voyage tokens, measured on embed_text). Top 5 x 800 = 4K tokens fits Groq's
# 8K tokens/min; M0's 60-line windows averaged ~430 tokens.
TARGET_MIN_TOKENS = 200  # a merged group stops growing once it reaches this
TARGET_MAX_TOKENS = 500  # merges, packed parts and windows never grow past this
MAX_TOKENS = 800  # hard cap on any chunk's embed_text
MIN_TOKENS = 60  # only units smaller than this are merged with siblings
WINDOW_OVERLAP_LINES = 0  # M3 ablation only; > 0 breaks the "one chunk per line" invariant
# End a full window at the last blank line in its final quarter, so windows break between
# functions/paragraphs. M3 runs the windows control both naive (False) and polished (True).
WINDOW_PREFER_BLANK_LINES = True
# A /** */ doc comment attaches to the next NAMED unit across one blank line (express puts a
# blank line between every JSDoc block and its function). `//` and Python `#` comments only
# attach with no blank line. M3 ablates this.
JSDOC_ATTACH_ACROSS_BLANK = True
EMBED_INCLUDE_PATH = True
EMBED_INCLUDE_SCOPE = True
MAX_CONTEXT_HEADERS = 3  # enclosing header lines carried by a split piece (innermost kept)
MAX_HEADER_LINE_CHARS = 200
OUTLINE_MAX_TOKENS = 120  # method outline in a class header chunk
MAX_NAMES_IN_SCOPE = 5  # merged chunk "a, b, c, d, e +2 more"

# ---------- Answering (M2) ----------
# Context the LLM sees, in Voyage tokens. Groq allows ~8K tokens/min per model (prompt +
# output), so ~2K of context keeps ~3 questions/min. Slice 2 calibrates this against
# usage.prompt_tokens.
CONTEXT_BUDGET_TOKENS = 2_000
# usage.prompt_tokens minus the context estimate was a near-constant +458..+652 in slice 1
# (system prompt, file tags, question): for capacity math and logs only, not the budget.
PROMPT_OVERHEAD_TOKENS = 700
# token_count measures embed_text, but the LLM sees every line with its absolute number
# ("182| "), which costs ~3 extra tokens per line.
LINE_NUMBER_TOKENS = 3
RETRIEVE_K = 15
# Chunks per file, counted before merging. None = no cap: the slice 2 comparison (PLAN.md Q28)
# found caps of 3-5 push weaker other-file chunks in. Provisional (one small repo); kept as a
# parameter for the M3 ablation.
PER_FILE_CAP: int | None = None
MERGE_MAX_GAP_LINES = 5  # blank lines two same-file chunks may have between them (Q21)
OUTLINE_MAX_NAMES = 20  # member names in a class outline (Q25)
CHARS_PER_TOKEN = 3  # for text without a stored token_count (outlines)
POSSIBLY_RELEVANT_FILES = 3  # files suggested when an answer has no valid citation (Q23)
# Defensive cap on the code blocks /ask sends for the panel (Q30). The 2K-token context budget
# keeps them near 8 KB; this only guards against a future budget change (Render bandwidth).
EVIDENCE_MAX_CHARS = 32_000

# ---------- Groq (free catalogue changes: never hardcode the model elsewhere) ----------
GROQ_MODEL = "qwen/qwen3.8-27b"  # chosen by the slice 1 comparison (PLAN.md, Q15)
# No model fallback: gpt-oss-120b missed the fallback rule (lenient citation validity 69% of
# qwen's; short paths). When qwen fails, the demo shows pre-generated answers and a notice.
GROQ_FALLBACK_MODEL = None
# Per-model request options (Groq docs, 2026-11-02): qwen can switch reasoning off; gpt-oss
# can't (low is the minimum) and returns its reasoning in a separate field unless told not to.
GROQ_MODEL_OPTIONS = {
    "qwen/qwen3.8-27b": {"reasoning_effort": "none"},
    "openai/gpt-oss-120b": {"reasoning_effort": "low", "include_reasoning": False},
}
# M0: qwen rejects a request outright if its possible output exceeds the 1,000 output
# tokens/min limit, so the cap must stay well below it.
ANSWER_MAX_TOKENS = 600
ANSWER_TEMPERATURE = 0
GROQ_TIMEOUT_S = 60
GROQ_MAX_RETRIES = 2  # per request, on 429 only
GROQ_MAX_RETRY_WAIT_S = 30  # a longer Retry-After is returned as an error, not waited out
GROQ_MODELS_TIMEOUT_S = 10  # the model-list check must not hold up /status for long
MODEL_CHECK_TTL_S = 600  # re-check that the model still exists at most this often (Q24)

# ---------- API ----------
# The only repos the public API answers about (Q1, Q12). CodeAsk itself joins once public.
FEATURED_REPOS = ("pallets/itsdangerous", "psf/requests", "expressjs/express")
