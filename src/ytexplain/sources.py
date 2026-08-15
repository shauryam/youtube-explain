"""Resolve YouTube URLs into concrete videos, and fetch lightweight metadata."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx

from .models import VideoMeta, VideoRef

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
PATH_PATTERNS = (
    re.compile(r"^/(?:shorts|embed|live|v)/(?P<id>[A-Za-z0-9_-]{11})"),
    re.compile(r"^/(?P<id>[A-Za-z0-9_-]{11})$"),  # youtu.be/<id>
)
OEMBED = "https://www.youtube.com/oembed"
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
PLAYLIST_URL = "https://www.youtube.com/playlist?list={playlist_id}"


class SourceError(RuntimeError):
    pass


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def extract_video_id(url: str) -> str | None:
    if VIDEO_ID.match(url.strip()):
        return url.strip()
    parsed = urlparse(url if "//" in url else f"https://{url}")
    if not parsed.netloc.endswith(("youtube.com", "youtu.be", "youtube-nocookie.com")):
        return None
    if values := parse_qs(parsed.query).get("v"):
        candidate = values[0]
        return candidate if VIDEO_ID.match(candidate) else None
    for pattern in PATH_PATTERNS:
        if match := pattern.match(parsed.path):
            return match.group("id")
    return None


def extract_playlist_id(url: str) -> str | None:
    values = _query(url).get("list")
    if not values:
        return None
    playlist_id = values[0]
    # "Watch later"/"my mix" style pseudo-playlists cannot be enumerated.
    return None if playlist_id.startswith(("RD", "UL", "WL", "LL")) else playlist_id


def resolve_targets(url: str, *, force_playlist: bool = False, limit: int | None = None) -> tuple[list[VideoRef], str | None]:
    """Return the videos to process plus the playlist title, when applicable.

    A `watch?v=...&list=...` URL is treated as a single video unless the caller
    explicitly asks for the whole playlist.
    """
    video_id = extract_video_id(url)
    playlist_id = extract_playlist_id(url)

    if playlist_id and (force_playlist or not video_id):
        refs, title = _enumerate_playlist(playlist_id, limit=limit)
        if refs:
            return refs, title
        if not video_id:
            raise SourceError(f"Could not read any videos from playlist {playlist_id}")

    if not video_id:
        raise SourceError(f"Not a recognisable YouTube video or playlist URL: {url}")
    return [VideoRef(video_id=video_id, url=WATCH_URL.format(video_id=video_id))], None


def _enumerate_playlist(playlist_id: str, *, limit: int | None = None) -> tuple[list[VideoRef], str | None]:
    from yt_dlp import (
        YoutubeDL,  # imported lazily: slow module, only needed for playlists
    )

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
    }
    if limit:
        options["playlistend"] = limit

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(PLAYLIST_URL.format(playlist_id=playlist_id), download=False)

    entries = [entry for entry in (info or {}).get("entries") or [] if entry]
    refs = [
        VideoRef(
            video_id=entry["id"],
            url=WATCH_URL.format(video_id=entry["id"]),
            title=entry.get("title"),
            playlist_index=index,
        )
        for index, entry in enumerate(entries, start=1)
        if entry.get("id") and VIDEO_ID.match(entry["id"])
    ]
    return refs, (info or {}).get("title")


def fetch_metadata(ref: VideoRef, *, playlist_title: str | None = None) -> VideoMeta:
    """Title and channel via oEmbed, which is fast and does not need yt-dlp."""
    title, channel = ref.title, None
    try:
        response = httpx.get(
            OEMBED, params={"url": ref.url, "format": "json"}, timeout=15, follow_redirects=True
        )
        if response.status_code == 200:
            payload = response.json()
            title = payload.get("title") or title
            channel = payload.get("author_name")
    except (httpx.HTTPError, ValueError):
        pass

    return VideoMeta(
        video_id=ref.video_id,
        url=ref.url,
        title=title or f"YouTube video {ref.video_id}",
        channel=channel,
        playlist_title=playlist_title,
        playlist_index=ref.playlist_index,
    )
