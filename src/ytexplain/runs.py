"""A JSON record written beside each PDF: where it came from and what it cost.

The PDF says nothing about the run that produced it, and the cost figures live only
in the summary line the CLI prints before exiting. Keeping a small sidecar means a
finished run stays inspectable, and the web UI can list history by reading the
output directory instead of needing a database. When queries matter -- spend per
month, filter by model -- this is the point at which SQLite earns its place.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path

from .files import write_atomic_text
from .models import Document, format_reading_time


@dataclass(slots=True)
class UsageDelta:
    """What one document cost, carved out of a client's running totals."""

    cost_usd: float = 0.0
    calls: int = 0
    cached_calls: int = 0

    @classmethod
    def between(cls, before, after) -> UsageDelta:
        # `Usage` accumulates over a whole run, so a per-document figure is the
        # difference either side of the build rather than the counter itself.
        return cls(
            cost_usd=round(after.cost_usd - before.cost_usd, 6),
            calls=after.calls - before.calls,
            cached_calls=after.cached_calls - before.cached_calls,
        )


@dataclass(slots=True)
class RunRecord:
    pdf: str
    url: str
    video_id: str
    title: str
    model: str
    sections: int
    words: int
    reading_time: str
    cost_usd: float
    calls: int
    cached_calls: int
    seconds: float
    generated_at: str
    videos: int = 1
    channel: str | None = None
    markdown: str | None = None


def record_path(pdf_path: Path) -> Path:
    return Path(pdf_path).with_suffix(".json")


def write_record(
    documents: Sequence[Document],
    pdf_path: Path,
    *,
    usage: UsageDelta,
    seconds: float,
    title: str | None = None,
    url: str | None = None,
    markdown_path: Path | None = None,
) -> RunRecord:
    """Describe one PDF. Takes a list because a combined playlist is one file too.

    `title` and `url` are overridden for a combined book, where the collection is
    what the reader asked for rather than any single video in it.

    Returns the record so a caller that has just generated one does not have to
    read it back; `record_path` says where it went.
    """
    pdf_path = Path(pdf_path)
    first = documents[0]
    single = len(documents) == 1
    words = sum(document.explainer.words for document in documents)
    record = RunRecord(
        # Just the filename: the record sits beside its PDF, so the pair can be
        # moved or deleted together without the path going stale.
        pdf=pdf_path.name,
        url=url or first.meta.url,
        video_id=first.meta.video_id if single else "",
        title=title or first.explainer.title,
        model=first.explainer.model,
        sections=sum(len(document.explainer.sections) for document in documents),
        words=words,
        reading_time=format_reading_time(words),
        cost_usd=usage.cost_usd,
        calls=usage.calls,
        cached_calls=usage.cached_calls,
        seconds=round(seconds, 1),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        videos=len(documents),
        channel=first.meta.channel if single else None,
        markdown=markdown_path.name if markdown_path else None,
    )
    write_atomic_text(record_path(pdf_path), json.dumps(asdict(record), indent=2))
    return record


def load_records(out_dir: Path) -> list[tuple[RunRecord, Path]]:
    """Every readable record under `out_dir`, newest first, paired with its PDF.

    Anything unreadable, malformed or orphaned is skipped rather than raised: a
    history list is not worth failing a page load over, and a half-deleted run
    should simply disappear from it.
    """
    known = {field.name for field in fields(RunRecord)}
    found: list[tuple[RunRecord, Path]] = []
    for path in Path(out_dir).rglob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            record = RunRecord(**{k: v for k, v in payload.items() if k in known})
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        pdf = path.parent / record.pdf
        if pdf.is_file():
            found.append((record, pdf))
    return sorted(found, key=lambda entry: entry[0].generated_at, reverse=True)
