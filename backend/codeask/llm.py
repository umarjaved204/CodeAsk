"""Groq chat completions over plain HTTP (like the Voyage embedder: no SDK on the query path,
and the rate-limit headers stay in our hands).

The API key goes only into the Authorization header and is never logged or returned.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from codeask import config

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Groq docs: *-requests = requests per day, *-tokens = tokens per minute (rolling).
RATE_HEADERS = ("x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
                "x-ratelimit-reset-requests", "x-ratelimit-limit-tokens",
                "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens", "retry-after")


class GroqError(Exception):
    pass


class RateLimited(GroqError):
    pass


@dataclass
class Reply:
    text: str  # message.content: the final answer (raw <think> tags possible, see answer.py)
    reasoning: str | None  # message.reasoning, when the model returns it separately
    usage: dict  # Groq's usage object as returned (the truth for token counts)
    headers: dict  # the raw rate-limit headers of the last response
    model: str
    latency_s: float  # wall time of the successful request
    retries: int  # 429s waited out before it


class GroqClient:
    def __init__(self, model: str = config.GROQ_MODEL, post=None, api_key: str | None = None,
                 sleep=time.sleep, clock=time.monotonic):
        self.model = model
        self._post, self._api_key = post, api_key
        self.sleep, self.clock = sleep, clock

    def _send(self, body: dict):
        if self._post is None:
            import requests

            self._post = requests.post
        if self._api_key is None:
            from dotenv import load_dotenv

            load_dotenv()
            self._api_key = os.environ["GROQ_API_KEY"]
        return self._post(GROQ_URL, json=body, timeout=config.GROQ_TIMEOUT_S,
                          headers={"Authorization": f"Bearer {self._api_key}"})

    def chat(self, messages: list[dict], max_tokens: int = config.ANSWER_MAX_TOKENS) -> Reply:
        body = {"model": self.model, "messages": messages, "temperature": 0,
                "max_completion_tokens": max_tokens,
                **config.GROQ_MODEL_OPTIONS.get(self.model, {})}
        for attempt in range(config.GROQ_MAX_RETRIES + 1):
            start = self.clock()
            response = self._send(body)
            headers = {k: response.headers[k] for k in RATE_HEADERS if k in response.headers}
            if response.status_code == 429:
                wait = float(headers.get("retry-after", config.GROQ_MAX_RETRY_WAIT_S + 1))
                if attempt == config.GROQ_MAX_RETRIES or wait > config.GROQ_MAX_RETRY_WAIT_S:
                    raise RateLimited(f"429 from Groq (retry-after {wait:g} s), headers {headers}")
                self.sleep(wait)
                continue
            if response.status_code != 200:
                # Groq's error body explains the problem (e.g. "Request too large"); it never
                # echoes the key.
                raise GroqError(f"Groq {response.status_code}: {response.text[:300]}")
            data = response.json()
            message = data["choices"][0]["message"]
            return Reply(message.get("content") or "", message.get("reasoning"),
                         data.get("usage", {}), headers, data.get("model", self.model),
                         round(self.clock() - start, 2), attempt)
