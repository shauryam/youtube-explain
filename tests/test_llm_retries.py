import httpx
import pytest

from ytexplain.llm import FatalLLMError, LLMError, OpenRouterClient


def client_with(responses, monkeypatch):
    """A client whose transport replays `responses`, counting the attempts."""
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return responses[min(len(attempts) - 1, len(responses) - 1)]

    client = OpenRouterClient("test-key", "vendor/model", max_retries=4)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ytexplain.llm.time.sleep", lambda _seconds: None)
    return client, attempts


def test_exhausted_credit_fails_on_the_first_attempt(monkeypatch):
    client, attempts = client_with(
        [httpx.Response(402, text="insufficient credits")], monkeypatch
    )

    with pytest.raises(FatalLLMError) as raised:
        client.complete(system="s", user="u")

    assert raised.value.status == 402
    assert len(attempts) == 1


@pytest.mark.parametrize("status", [400, 401, 404])
def test_other_client_errors_also_fail_immediately(status, monkeypatch):
    client, attempts = client_with([httpx.Response(status, text="nope")], monkeypatch)

    with pytest.raises(FatalLLMError):
        client.complete(system="s", user="u")

    assert len(attempts) == 1


def test_server_errors_still_use_every_retry(monkeypatch):
    client, attempts = client_with([httpx.Response(503, text="try later")], monkeypatch)

    with pytest.raises(LLMError) as raised:
        client.complete(system="s", user="u")

    assert not isinstance(raised.value, FatalLLMError)
    assert len(attempts) == 5  # the first attempt plus max_retries


def test_a_retry_can_succeed(monkeypatch):
    payload = {
        "choices": [{"message": {"content": "written"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    client, attempts = client_with(
        [httpx.Response(429, text="slow down"), httpx.Response(200, json=payload)],
        monkeypatch,
    )

    assert client.complete(system="s", user="u") == "written"
    assert len(attempts) == 2
