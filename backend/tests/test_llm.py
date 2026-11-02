import pytest

from codeask import config
from codeask.llm import GroqClient, GroqError, RateLimited

KEY = "gsk_test_secret"


class FakeResponse:
    def __init__(self, status=200, json=None, headers=None, text=""):
        self.status_code, self._json, self.headers, self.text = status, json, headers or {}, text

    def json(self):
        return self._json


def ok(content="Answer [a.py:1-2]", reasoning=None):
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning"] = reasoning
    return FakeResponse(200, {"model": "m", "choices": [{"message": message}],
                              "usage": {"prompt_tokens": 900, "completion_tokens": 120}},
                        {"x-ratelimit-remaining-tokens": "7000", "x-ratelimit-limit-requests":
                         "1000", "content-type": "application/json"})


class FakePost:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, url, json, timeout, headers):
        self.calls.append({"url": url, "json": json, "timeout": timeout, "headers": headers})
        return self.responses.pop(0)


def client(*responses, model="qwen/qwen3.8-27b"):
    post, slept = FakePost(*responses), []
    return GroqClient(model, post=post, api_key=KEY, sleep=slept.append), post, slept


def test_request_sets_output_limit_temperature_and_model_options_explicitly():
    c, post, _ = client(ok())
    c.chat([{"role": "user", "content": "q"}], max_tokens=600)
    body = post.calls[0]["json"]
    assert body["temperature"] == 0 and body["max_completion_tokens"] == 600
    assert body["reasoning_effort"] == "none" and "max_tokens" not in body
    assert post.calls[0]["timeout"] == config.GROQ_TIMEOUT_S


def test_gpt_oss_gets_its_own_reasoning_options():
    c, post, _ = client(ok(), model="openai/gpt-oss-120b")
    c.chat([])
    assert post.calls[0]["json"]["reasoning_effort"] == "low"
    assert post.calls[0]["json"]["include_reasoning"] is False


def test_reply_keeps_answer_reasoning_usage_and_only_rate_limit_headers():
    c, _, _ = client(ok(content="Final", reasoning="thinking..."))
    reply = c.chat([])
    assert (reply.text, reply.reasoning) == ("Final", "thinking...")
    assert reply.usage == {"prompt_tokens": 900, "completion_tokens": 120}
    assert reply.headers == {"x-ratelimit-remaining-tokens": "7000",
                             "x-ratelimit-limit-requests": "1000"}


def test_429_waits_retry_after_then_succeeds():
    c, post, slept = client(FakeResponse(429, headers={"retry-after": "7"}), ok())
    reply = c.chat([])
    assert slept == [7.0] and reply.retries == 1 and len(post.calls) == 2


def test_429_with_a_long_retry_after_is_an_error_not_a_long_wait():
    c, _, slept = client(FakeResponse(429, headers={"retry-after": "120"}))
    with pytest.raises(RateLimited):
        c.chat([])
    assert slept == []


def test_429_on_every_attempt_raises():
    responses = [FakeResponse(429, headers={"retry-after": "1"})] * (config.GROQ_MAX_RETRIES + 1)
    c, _, slept = client(*responses)
    with pytest.raises(RateLimited):
        c.chat([])
    assert len(slept) == config.GROQ_MAX_RETRIES


def test_other_errors_raise_with_groq_message_and_never_the_key():
    c, _, _ = client(FakeResponse(400, text='{"error": "Request too large"}'))
    with pytest.raises(GroqError) as err:
        c.chat([])
    assert "Request too large" in str(err.value) and KEY not in str(err.value)


def test_key_goes_only_into_the_authorization_header():
    c, post, _ = client(ok())
    reply = c.chat([])
    assert post.calls[0]["headers"] == {"Authorization": f"Bearer {KEY}"}
    assert KEY not in repr(reply) and KEY not in repr(post.calls[0]["json"])
