"""Exact token counts with Voyage's tokenizer. It runs locally (downloaded from Hugging Face
on first use), so counting never spends API quota."""

from __future__ import annotations

import os
from typing import Callable

from codeask import config


def voyage_counter(model: str = config.EMBED_MODEL) -> Callable[[str], int]:
    import voyageai
    from dotenv import load_dotenv

    load_dotenv()
    client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"], max_retries=0)
    cache: dict[str, int] = {}  # blank lines, braces and imports repeat a lot

    def count(text: str) -> int:
        n = cache.get(text)
        if n is None:
            n = cache[text] = client.count_tokens([text], model=model)
        return n

    return count
