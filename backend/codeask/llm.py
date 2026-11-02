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


GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"


class GroqError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status  # Groq's HTTP status (404 = the model is gone)


class RateLimited(GroqError):
    def __init__(self, message: str, retry_after: float):
        super().__init__(message, 429)
        self.retry_after = retry_after


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
                 sleep=time.sleep, clock=time.monotonic, get=None):
        self.model = model
        self._post, self._get, self._api_key = post, get, api_key
        self.sleep, self.clock = sleep, clock

    def _auth(self) -> dict:
        if self._api_key is None:
            from dotenv import load_dotenv

            load_dotenv()
            self._api_key = os.environ["GROQ_API_KEY"]
        return {"Authorization": f"Bearer {self._api_key}"}

    def _send(self, body: dict):
        if self._post is None:
            import requests

            self._post = requests.post
        return self._post(GROQ_URL, json=body, timeout=config.GROQ_TIMEOUT_S,
                          headers=self._auth())

    def available_models(self) -> set[str]:
        """Model ids Groq currently serves to this key (the startup and TTL check, Q24)."""
        if self._get is None:
            import requests

            self._get = requests.get
        response = self._get(GROQ_MODELS_URL, timeout=config.GROQ_MODELS_TIMEOUT_S,
                             headers=self._auth())
        if response.status_code != 200:
            raise GroqError(f"Groq models {response.status_code}", response.status_code)
        return {m["id"] for m in response.json()["data"]}

    def chat(self, messages: list[dict], max_tokens: int = config.ANSWER_MAX_TOKENS) -> Reply:
        body = {"model": self.model, "messages": messages,
                "temperature": config.ANSWER_TEMPERATURE,
                "max_completion_tokens": max_tokens,
                **config.GROQ_MODEL_OPTIONS.get(self.model, {})}
        for attempt in range(config.GROQ_MAX_RETRIES + 1):
            start = self.clock()
            response = self._send(body)
            headers = {k: response.headers[k] for k in RATE_HEADERS if k in response.headers}
            if response.status_code == 429:
                wait = float(headers.get("retry-after", config.GROQ_MAX_RETRY_WAIT_S + 1))
                if attempt == config.GROQ_MAX_RETRIES or wait > config.GROQ_MAX_RETRY_WAIT_S:
                    raise RateLimited(f"429 from Groq (retry-after {wait:g} s), headers {headers}",
                                      wait)
                self.sleep(wait)
                continue
            if response.status_code != 200:
                # Groq's error body explains the problem (e.g. "Request too large"); it never
                # echoes the key.
                raise GroqError(f"Groq {response.status_code}: {response.text[:300]}",
                                response.status_code)
            data = response.json()
            message = data["choices"][0]["message"]
            return Reply(message.get("content") or "", message.get("reasoning"),
                         data.get("usage", {}), headers, data.get("model", self.model),
                         round(self.clock() - start, 2), attempt)
