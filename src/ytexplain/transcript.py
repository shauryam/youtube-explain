"""Fetch the best available caption track for a video.

Primary path is youtube-transcript-api. When YouTube blocks that (rate limits,
datacenter IPs, consent walls) we fall back to yt-dlp, which negotiates a full
player response and can usually still hand us caption URLs.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from .cache import Cache
from .models import Segment, Transcript

PREFERRED = ("en", "en-US", "en-GB")


class TranscriptError(RuntimeError):
    pass


def get_transcript(
    video_id: str,
    *,
    cache: Cache | None = None,
    languages: tuple[str, ...] = PREFERRED,
) -> Transcript:
    key = Cache.key("transcript", video_id, languages)
    if cache and (payload := cache.get("transcripts", key)):
        return _from_payload(payload)

    errors: list[str] = []
    for loader in (_via_api, _via_ytdlp):
        try:
            transcript = loader(video_id, languages)
        except Exception as exc:  # noqa: BLE001 - both backends raise many types
            errors.append(f"{loader.__name__.lstrip('_')}: {exc}")
            continue
        if transcript.segments:
            if cache:
                cache.set("transcripts", key, _to_payload(transcript))
            return transcript
        errors.append(f"{loader.__name__.lstrip('_')}: empty transcript")

    raise TranscriptError(
        f"No captions could be retrieved for {video_id}. Tried: " + " | ".join(errors)
    )


def _to_payload(transcript: Transcript) -> dict:
    return {
        "language_code": transcript.language_code,
        "is_generated": transcript.is_generated,
        "source": transcript.source,
        "segments": [asdict(s) for s in transcript.segments],
    }


def _from_payload(payload: dict) -> Transcript:
    return Transcript(
        segments=[Segment(**s) for s in payload["segments"]],
        language_code=payload["language_code"],
        is_generated=payload["is_generated"],
        source=payload["source"],
    )


def _via_api(video_id: str, languages: tuple[str, ...]) -> Transcript:
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    available = api.list(video_id)
    track = _choose_track(available, languages)
    fetched = track.fetch()
    segments = [
        Segment(start=float(s.start), duration=float(s.duration), text=_clean(s.text))
        for s in fetched
    ]
    return Transcript(
        segments=[s for s in segments if s.text],
        language_code=track.language_code,
        is_generated=track.is_generated,
        source="youtube-transcript-api",
    )


def _choose_track(available, languages: tuple[str, ...]):
    """Prefer human captions over auto-generated, and English over anything else."""
    from youtube_transcript_api import NoTranscriptFound

    for finder in (
        available.find_manually_created_transcript,
        available.find_generated_transcript,
    ):
        try:
            return finder(list(languages))
        except NoTranscriptFound:
            continue

    tracks = list(available)
    if not tracks:
        raise TranscriptError("video has no caption tracks")
    manual = [t for t in tracks if not t.is_generated]
    return (manual or tracks)[0]


def _via_ytdlp(video_id: str, languages: tuple[str, ...]) -> Transcript:
    from yt_dlp import YoutubeDL

    options = {"quiet": True, "no_warnings": True, "skip_download": True}
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        manual = (info or {}).get("subtitles") or {}
        auto = (info or {}).get("automatic_captions") or {}
        language, tracks, generated = _choose_ytdlp_track(manual, auto, languages)
        url = _json3_url(tracks)
        if not url:
            raise TranscriptError("no json3 caption format offered")
        raw = ydl.urlopen(url).read().decode("utf-8", "replace")

    return Transcript(
        segments=_parse_json3(raw),
        language_code=language,
        is_generated=generated,
        source="yt-dlp",
    )


def _choose_ytdlp_track(manual: dict, auto: dict, languages: tuple[str, ...]):
    for pool, generated in ((manual, False), (auto, True)):
        for language in languages:
            for code in (language, language.split("-")[0]):
                if code in pool:
                    return code, pool[code], generated
        if pool:
            code = next(iter(pool))
            return code, pool[code], generated
    raise TranscriptError("video has no caption tracks")


def _json3_url(tracks: list[dict]) -> str | None:
    for track in tracks:
        if track.get("ext") == "json3" and track.get("url"):
            return track["url"]
    return None


def _parse_json3(raw: str) -> list[Segment]:
    events = json.loads(raw).get("events") or []
    segments = []
    for event in events:
        text = _clean("".join(seg.get("utf8", "") for seg in event.get("segs") or []))
        if not text:
            continue
        segments.append(
            Segment(
                start=float(event.get("tStartMs", 0)) / 1000.0,
                duration=float(event.get("dDurationMs", 0)) / 1000.0,
                text=text,
            )
        )
    return segments


def _clean(text: str) -> str:
    return " ".join(text.replace("\n", " ").split()).strip()
