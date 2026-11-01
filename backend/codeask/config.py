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
BATCH_TOKENS = 3_000  # M0: 9K-token requests were never accepted; 3K worked

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
EMBED_INCLUDE_PATH = True
EMBED_INCLUDE_SCOPE = True
MAX_CONTEXT_HEADERS = 3  # enclosing header lines carried by a split piece (innermost kept)
MAX_HEADER_LINE_CHARS = 200
OUTLINE_MAX_TOKENS = 120  # method outline in a class header chunk
MAX_NAMES_IN_SCOPE = 5  # merged chunk "a, b, c, d, e +2 more"
