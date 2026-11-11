import pytest

from codeask import config
from codeask.deadline import DeadlineExceeded
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


def test_rate_limit_and_status_are_carried_on_the_exceptions():
    c, _, _ = client(FakeResponse(429, headers={"retry-after": "45"}))
    with pytest.raises(RateLimited) as err:
        c.chat([])  # 45 s > GROQ_MAX_RETRY_WAIT_S: returned, not waited out
    assert (err.value.retry_after, err.value.status) == (45.0, 429)
    c, _, _ = client(FakeResponse(404, text='{"error": "model_not_found"}'))
    with pytest.raises(GroqError) as err:
        c.chat([])
    assert err.value.status == 404


def test_available_models_lists_ids_with_a_short_timeout_and_the_key_only_in_the_header():
    calls = []

    def get(url, timeout, headers):
        calls.append((url, timeout, headers))
        return FakeResponse(200, {"data": [{"id": "qwen/qwen3.8-27b"}, {"id": "other"}]})

    c = GroqClient(get=get, api_key=KEY)
    assert c.available_models() == {"qwen/qwen3.8-27b", "other"}
    assert calls == [("https://api.groq.com/openai/v1/models", config.GROQ_MODELS_TIMEOUT_S,
                      {"Authorization": f"Bearer {KEY}"})]
    c = GroqClient(get=lambda url, timeout, headers: FakeResponse(401), api_key=KEY)
    with pytest.raises(GroqError):
        c.available_models()


# ---------- with a deadline (an /ask, Q43); the clock is frozen at 0 ----------
def timed(*responses):
    post, slept = FakePost(*responses), []
    return GroqClient(post=post, api_key=KEY, sleep=slept.append, clock=lambda: 0.0), post, slept


def test_the_request_timeout_is_capped_at_the_time_left():
    c, post, _ = timed(ok())
    c.chat([], deadline=20)
    assert post.calls[0]["timeout"] == 20


def test_no_request_once_the_deadline_has_passed():
    c, post, _ = timed()
    with pytest.raises(DeadlineExceeded):
        c.chat([], deadline=0)
    assert post.calls == []


def test_a_429_wait_longer_than_the_time_left_is_not_waited():
    c, _, slept = timed(FakeResponse(429, headers={"retry-after": "7"}))
    with pytest.raises(RateLimited):
        c.chat([], deadline=5)
    assert slept == []


def test_a_429_is_retried_at_most_once_with_a_deadline():
    c, post, slept = timed(*[FakeResponse(429, headers={"retry-after": "1"})] * 2)
    with pytest.raises(RateLimited):
        c.chat([], deadline=60)
    assert (len(post.calls), slept) == (2, [1.0])


def test_a_groq_5xx_is_retried_once_then_succeeds():
    c, post, _ = timed(FakeResponse(503, text="overloaded"), ok())
    assert c.chat([], deadline=60).text == "Answer [a.py:1-2]"
    assert len(post.calls) == 2
    c, post, _ = timed(FakeResponse(500, text="a"), FakeResponse(502, text="b"))
    with pytest.raises(GroqError):
        c.chat([], deadline=60)
    assert len(post.calls) == 2
