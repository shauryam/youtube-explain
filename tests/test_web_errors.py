import pytest

from ytexplain.config import ConfigError
from ytexplain.llm import FatalLLMError, LLMError, UpstreamError
from ytexplain.sources import SourceError
from ytexplain.transcript import TranscriptError
from ytexplain.web.errors import PlaylistUnsupported, classify

SECRET = "sk-or-v1-realkeyleaked"


@pytest.mark.parametrize(
    ("error", "kind", "retryable"),
    [
        (PlaylistUnsupported("That link is a playlist of 9 videos."), "playlist_unsupported", False),
        (SourceError("Not a recognisable YouTube URL: hello"), "invalid_url", False),
        (TranscriptError("no captions"), "no_captions", False),
        (FatalLLMError("HTTP 402: no credit", 402), "credits", False),
        (FatalLLMError("HTTP 401: bad key", 401), "auth_upstream", False),
        (FatalLLMError("HTTP 400: bad slug", 400), "model_refused", False),
        (FatalLLMError("HTTP 451: who knows", 451), "model_refused", False),
        (UpstreamError("HTTP 429: slow down", 429), "rate_limited", True),
        (UpstreamError("HTTP 503: overloaded", 503), "upstream", True),
        (UpstreamError("connection reset"), "upstream", True),
        (LLMError("Model did not return valid JSON"), "model_output", True),
        (ConfigError("OPENROUTER_API_KEY is not set"), "config", False),
        (OSError("No space left on device"), "output", True),
        (ZeroDivisionError("division by zero"), "unknown", True),
    ],
)
def test_each_failure_maps_to_a_kind_the_page_can_act_on(error, kind, retryable):
    mapped = classify(error)
    assert (mapped.kind, mapped.retryable) == (kind, retryable)
    assert mapped.message  # never an empty bubble in the UI


@pytest.mark.parametrize(
    "error",
    [
        TranscriptError(f"yt-dlp failed, cookies from 10.0.0.1, key {SECRET}"),
        FatalLLMError(f'HTTP 401: {{"error": "invalid key {SECRET}"}}', 401),
        UpstreamError(f"HTTP 503: upstream {SECRET}", 503),
        LLMError(f"Model did not return valid JSON: {SECRET}"),
        ZeroDivisionError(SECRET),
    ],
)
def test_upstream_text_never_reaches_the_browser(error):
    # These messages are shown on a page that may be shared or screenshotted; the
    # detail belongs in the server log, which is where the worker puts it.
    assert SECRET not in classify(error).message


def test_the_messages_users_can_act_on_keep_their_own_wording():
    # Where the engine's own sentence is the useful one, it is passed through.
    assert classify(SourceError("Not a YouTube URL: hello")).message.endswith("hello")
    assert "9 videos" in classify(PlaylistUnsupported("A playlist of 9 videos.")).message
