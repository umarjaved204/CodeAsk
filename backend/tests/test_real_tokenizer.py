"""The one test that uses the real Voyage tokenizer (local; downloaded from Hugging Face on
first run, no API request). Skipped by default; run with: pytest -m slow
"""

import os
from pathlib import Path

import pytest
from helpers import check_invariants

from codeask.chunker import ChunkSettings, chunk_file
from codeask.filters import decode

SIGNER = Path(__file__).resolve().parents[2] / "repos/itsdangerous/src/itsdangerous/signer.py"


@pytest.mark.slow
def test_real_tokenizer_respects_the_cap():
    voyageai = pytest.importorskip("voyageai")
    from dotenv import load_dotenv

    load_dotenv()
    if not os.environ.get("VOYAGE_API_KEY"):
        pytest.skip("VOYAGE_API_KEY not set")
    if not SIGNER.exists():
        pytest.skip("repos/itsdangerous not cloned")
    client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"], max_retries=0)

    def count(text):
        return client.count_tokens([text], model="voyage-code-3")

    # A cap small enough that the Signer class (~190 lines) must split.
    settings = ChunkSettings(max_tokens=300, target_max=200, target_min=100, min_tokens=30)
    text = decode(SIGNER.read_bytes())
    result = chunk_file("src/itsdangerous/signer.py", text, count, settings)

    check_invariants(text, result, settings.max_tokens)
    # Signer's header (class line + 37-line docstring + attributes) is over this cap, so it is
    # windowed; part 1 must still be the class_header carrying the method outline.
    header = next(c for c in result.chunks if c.kind == "class_header")
    assert header.breadcrumb.startswith("Signer")
    assert "Members:" in header.embed_text and "def derive_key" in header.embed_text
    # Whole, or split into "Signer > derive_key (part i/n)" if it's over the small cap.
    assert any(c.breadcrumb.startswith("Signer > derive_key") for c in result.chunks)
