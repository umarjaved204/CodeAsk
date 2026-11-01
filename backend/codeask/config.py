"""Tunable settings in one place. Most are starting guesses that the M3 eval will tune."""

# ---------- File filters ----------
MAX_FILE_BYTES = 100_000
# Data-like / minified code. TableTalk's longest real line is 196 chars. At ~2 chars/token
# (symbol-heavy code) 1,500 chars is ~750 tokens, just under the chunk cap.
MAX_LINE_CHARS = 1_500
MAX_AVG_LINE_CHARS = 200
# Generated-file markers are only looked for in the first few lines.
MARKER_LINES = 5
