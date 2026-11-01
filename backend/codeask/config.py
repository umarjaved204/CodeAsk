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
