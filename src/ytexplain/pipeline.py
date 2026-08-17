"""Glue the stages together: URL -> transcript -> explainer -> Document."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .cache import Cache
from .config import Settings
from .explain import build_explainer
from .llm import OpenRouterClient
from .models import Document, VideoRef
from .sources import fetch_metadata, resolve_targets
from .transcript import PREFERRED, get_transcript

SLUG_STRIP = re.compile(r"[^a-z0-9]+")
ProgressHook = Callable[[str], None]


@dataclass(slots=True)
class Options:
    fast: bool = False
    concurrency: int = 4
    languages: tuple[str, ...] = PREFERRED
    force_playlist: bool = False
    max_videos: int | None = None


def parse_languages(text: str) -> tuple[str, ...]:
    """Turn a comma-separated language list into a preference ladder."""
    languages = tuple(part.strip() for part in text.split(",") if part.strip())
    return languages or PREFERRED


def slugify(text: str, limit: int = 70) -> str:
    slug = SLUG_STRIP.sub("-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "untitled"


def collect(url: str, options: Options) -> tuple[list[VideoRef], str | None]:
    return resolve_targets(
        url, force_playlist=options.force_playlist, limit=options.max_videos
    )


def build_document(
    ref: VideoRef,
    *,
    client: OpenRouterClient,
    cache: Cache,
    options: Options,
    playlist_title: str | None = None,
    on_progress: ProgressHook | None = None,
) -> Document:
    notify = on_progress or (lambda _message: None)

    notify("Reading video details")
    meta = fetch_metadata(ref, playlist_title=playlist_title)

    notify("Fetching transcript")
    transcript = get_transcript(ref.video_id, cache=cache, languages=options.languages)
    meta.duration = meta.duration or transcript.duration
    notify(
        f"Transcript: {len(transcript.segments)} cues, {transcript.language_code}"
        f"{' (auto)' if transcript.is_generated else ''}"
    )

    explainer = build_explainer(
        transcript,
        meta,
        client,
        fast=options.fast,
        concurrency=options.concurrency,
        on_progress=notify,
    )
    return Document(meta=meta, explainer=explainer, transcript=transcript)


def make_client(settings: Settings, cache: Cache) -> OpenRouterClient:
    return OpenRouterClient(settings.require_api_key(), settings.model, cache=cache)


def output_path(
    document: Document,
    settings: Settings,
    *,
    explicit: Path | None = None,
    folder: Path | None = None,
    index: int | None = None,
) -> Path:
    if explicit:
        return explicit
    name = slugify(document.explainer.title)
    if index is not None:
        name = f"{index:02d}-{name}"
    return (folder or settings.output_dir) / f"{name}.pdf"
