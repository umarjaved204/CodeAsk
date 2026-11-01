import pytest

from codeask import config
from codeask.embedder import Limiter, RateLimited, VoyageEmbedder


class FakeResponse:
    def __init__(self, status, data=None):
        self.status_code, self._data = status, data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"data": self._data}


def make(responses):
    sent, slept, now = [], [], [0.0]

    def post(url, json, timeout, headers):
        sent.append(json)
        return responses.pop(0)

    # A fake clock that sleeping advances. A frozen clock would make the limiter wait forever
    # once 3 attempts fill its window (this test file once hung that way).
    def advance(seconds):
        now[0] += seconds

    def embedder_sleep(seconds):
        slept.append(seconds)
        advance(seconds)

    limiter = Limiter(clock=lambda: now[0], sleep=advance)
    embedder = VoyageEmbedder(limiter, post=post, api_key="test", sleep=embedder_sleep,
                              log=lambda *a: None)
    return embedder, sent, slept


def test_request_body_and_order_by_index():
    embedder, sent, _ = make([FakeResponse(200, [{"index": 1, "embedding": [2.0]},
                                                 {"index": 0, "embedding": [1.0]}])])
    assert embedder.embed(["a", "b"], "query") == [[1.0], [2.0]]
    assert sent == [{"input": ["a", "b"], "model": config.EMBED_MODEL, "input_type": "query",
                     "output_dimension": config.EMBED_DIM, "truncation": False}]


def test_429_waits_one_window_then_retries():
    embedder, sent, slept = make([FakeResponse(429), FakeResponse(200, [{"index": 0,
                                                                        "embedding": [1.0]}])])
    assert embedder.embed(["a"]) == [[1.0]]
    assert (embedder.calls, embedder.rate_limited) == (2, 1)
    assert slept == [config.VOYAGE_WINDOW_SECONDS]


def test_429_on_every_attempt_raises():
    embedder, _, _ = make([FakeResponse(429)] * (config.VOYAGE_MAX_RETRIES + 1))
    with pytest.raises(RateLimited):
        embedder.embed(["a"])


def test_other_errors_stop_immediately():
    embedder, sent, _ = make([FakeResponse(401)])
    with pytest.raises(RuntimeError):
        embedder.embed(["a"])
    assert len(sent) == 1  # no retry on a non-429 error
