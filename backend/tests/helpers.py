"""Shared test helpers (imported by test modules; pytest puts this folder on sys.path)."""


import hashlib
import random


class FakeEmbedder:
    """Deterministic stand-in for VoyageEmbedder: same text -> same 1024-d vector, no network.
    Records every text it embeds. fail_after=N raises KeyboardInterrupt on call N+1, which
    simulates Ctrl+C mid-ingest."""

    space = "fake:1024:document"

    def __init__(self, fail_after=None):
        self.fail_after = fail_after
        self.calls = 0
        self.texts = []

    def embed(self, texts, input_type="document"):
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise KeyboardInterrupt
        self.calls += 1
        self.texts.extend(texts)
        return [fake_vector(t) for t in texts]


def fake_vector(text, dim=1024):
    rng = random.Random(hashlib.sha256(text.encode("utf-8")).digest())
    return [rng.uniform(-1, 1) for _ in range(dim)]


def fake_count(text: str) -> int:
    """Stand-in tokenizer: ~4 chars per token. Fast, deterministic, no download."""
    return (len(text) + 3) // 4


def check_invariants(text, result, max_tokens):
    """The chunker's contract, for any file:
    - chunks are ascending and non-overlapping;
    - lines are 1-based inclusive and content == file_lines[start-1:end];
    - no chunk's embed_text exceeds the cap;
    - every non-blank line is in exactly one chunk, so joining the chunks reproduces the
      file's non-blank lines in order.
    """
    lines = text.split("\n")
    prev_end, covered = 0, []
    for c in result.chunks:
        where = f"chunk {c.start_line}-{c.end_line} ({c.kind}, {c.breadcrumb})"
        assert 1 <= c.start_line <= c.end_line <= len(lines), where
        assert c.start_line > prev_end, f"overlap or out of order at {where}"
        assert c.content == "\n".join(lines[c.start_line - 1:c.end_line]), where
        assert c.token_count <= max_tokens, f"{where}: {c.token_count} > {max_tokens}"
        prev_end = c.end_line
        covered.extend(range(c.start_line, c.end_line + 1))
    nonblank = [i for i, line in enumerate(lines, 1) if line.strip()]
    covered_nonblank = [i for i in covered if lines[i - 1].strip()]
    missing = sorted(set(nonblank) - set(covered_nonblank))
    assert covered_nonblank == nonblank, f"uncovered non-blank lines: {missing[:10]}"
