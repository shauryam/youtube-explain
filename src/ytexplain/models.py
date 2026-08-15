"""Shared data structures passed between the pipeline stages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

DEVANAGARI = re.compile(r"[\u0900-\u097F]")
NON_LATIN = re.compile(r"[^\x00-\x7F\u00A0-\u024F\u2000-\u206F]")


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


@dataclass(slots=True)
class VideoRef:
    """A video we intend to process, before any network work happens."""

    video_id: str
    url: str
    title: str | None = None
    playlist_index: int | None = None


@dataclass(slots=True)
class VideoMeta:
    video_id: str
    url: str
    title: str
    channel: str | None = None
    duration: float | None = None
    playlist_title: str | None = None
    playlist_index: int | None = None


@dataclass(slots=True)
class Segment:
    start: float
    duration: float
    text: str

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass(slots=True)
class Transcript:
    segments: list[Segment]
    language_code: str
    is_generated: bool
    source: str

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segments if s.text)

    @property
    def duration(self) -> float:
        return self.segments[-1].end if self.segments else 0.0

    @property
    def script(self) -> str:
        sample = self.text[:4000]
        if DEVANAGARI.search(sample):
            return "devanagari"
        return "non-latin" if NON_LATIN.search(sample) else "latin"

    @property
    def is_english(self) -> bool:
        return self.language_code.split("-")[0].lower() == "en" and self.script == "latin"

    def blocks(self, window: float = 30.0) -> list[tuple[float, str]]:
        """Merge fine-grained caption cues into coarser timestamped blocks.

        Auto-generated captions arrive in 2-5 second fragments; collapsing them
        keeps the timestamps the model needs without wasting tokens on them.
        """
        merged: list[tuple[float, list[str]]] = []
        for segment in self.segments:
            if not segment.text:
                continue
            if merged and segment.start - merged[-1][0] < window:
                merged[-1][1].append(segment.text)
            else:
                merged.append((segment.start, [segment.text]))
        return [(start, " ".join(parts)) for start, parts in merged]

    def timestamped_text(self, window: float = 30.0) -> str:
        return "\n".join(
            f"[{format_timestamp(start)}] {text}" for start, text in self.blocks(window)
        )

    def slice_text(
        self, start: float, end: float, padding: float = 45.0, window: float = 30.0
    ) -> str:
        low, high = start - padding, end + padding
        lines = [
            f"[{format_timestamp(ts)}] {text}"
            for ts, text in self.blocks(window)
            if low <= ts <= high
        ]
        return "\n".join(lines)


@dataclass(slots=True)
class Section:
    heading: str
    focus: str = ""
    start: float = 0.0
    end: float = 0.0
    body: str = ""


@dataclass(slots=True)
class Explainer:
    title: str
    abstract: str = ""
    prerequisites: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    key_terms: list[tuple[str, str]] = field(default_factory=list)
    takeaways: list[str] = field(default_factory=list)
    source_language: str = ""
    translated: bool = False
    model: str = ""


@dataclass(slots=True)
class Document:
    """One rendered chapter of a PDF: a video plus everything derived from it."""

    meta: VideoMeta
    explainer: Explainer
    transcript: Transcript
