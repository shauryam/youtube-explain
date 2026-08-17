"""One place that decides what a failure means to somebody looking at a browser.

The engine raises exceptions written for a terminal: exact, detailed, and often
carrying a slab of upstream response body. A browser needs the opposite — a short
sentence, and a machine-readable `kind` so the page can offer the right next step
(top up credit, pick another video, just press retry) without matching on prose.

Raw upstream text is deliberately dropped here. It goes to the server log, where
it is useful, rather than to a page that may be shared or screenshotted.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import ConfigError
from ..llm import FatalLLMError, LLMError, UpstreamError
from ..sources import SourceError
from ..transcript import TranscriptError


class PlaylistUnsupported(RuntimeError):
    """A URL expanded to more than one video, which the web UI does not do yet."""


@dataclass(slots=True)
class JobError:
    kind: str
    message: str
    retryable: bool


# Statuses OpenRouter uses for problems the server operator has to fix.
FATAL_STATUS: dict[int, tuple[str, str]] = {
    400: (
        "model_refused",
        "The model rejected the request. The slug may be wrong, or it may not accept these options.",
    ),
    401: ("auth_upstream", "OpenRouter rejected this server's API key."),
    403: ("auth_upstream", "OpenRouter refused the request for this API key."),
    404: ("model_refused", "That model does not exist on OpenRouter."),
    402: (
        "credits",
        "The OpenRouter account is out of credit. Add some and the run will pick up from the cache.",
    ),
}

UNKNOWN = ("unknown", "Something went wrong on the server. The log has the details.", True)


def classify(exc: BaseException) -> JobError:
    """Map an engine exception onto the failure the UI should show."""
    if isinstance(exc, PlaylistUnsupported):
        return JobError("playlist_unsupported", str(exc), False)
    if isinstance(exc, SourceError):
        return JobError("invalid_url", str(exc), False)
    if isinstance(exc, TranscriptError):
        # The commonest real failure: no captions means there is nothing to explain.
        return JobError(
            "no_captions",
            "No captions could be read for this video, so there is nothing to explain."
            " Music videos and some uploads have captions disabled.",
            False,
        )
    if isinstance(exc, FatalLLMError):
        kind, message = FATAL_STATUS.get(
            exc.status, ("model_refused", "OpenRouter rejected the request.")
        )
        return JobError(kind, message, False)
    if isinstance(exc, UpstreamError):
        if exc.status == 429:
            return JobError(
                "rate_limited",
                "OpenRouter is rate limiting this key. Waiting a minute usually clears it.",
                True,
            )
        return JobError(
            "upstream",
            "OpenRouter could not be reached, or kept failing. Retrying is safe.",
            True,
        )
    if isinstance(exc, LLMError):
        # Reached the model, came back unusable. A retry replays the cached calls
        # and only redoes the broken one, so it is cheap as well as worthwhile.
        return JobError(
            "model_output",
            "The model's answer could not be used. Retrying usually fixes it, and finished work is cached.",
            True,
        )
    if isinstance(exc, ConfigError):
        return JobError("config", str(exc), False)
    if isinstance(exc, OSError):
        return JobError("output", "The PDF could not be written on the server.", True)
    return JobError(*UNKNOWN)
