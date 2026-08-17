"""Jobs: one submitted URL, run in the background, watched by polling.

Job state lives in this process and nowhere else. That is a deliberate trade: the
things worth keeping — the PDF, the markdown, the run record — are already on disk
the moment a run finishes, so a restart costs at most the progress lines of a job
that was still running. A database here would add a schema, a migration story and
a second source of truth about what `out/` contains, to protect information that
stops being interesting a second after the PDF appears.

Runs are serial. One `ThreadPoolExecutor` worker means two submissions cannot race
each other into the OpenRouter balance or get the machine rate-limited by YouTube,
and it makes `queued` an honest status rather than a fiction.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..cache import Cache
from ..config import Settings
from ..files import write_atomic_text
from ..pipeline import (
    Options,
    build_document,
    collect,
    make_client,
    output_path,
    parse_languages,
)
from ..render import build_pdf
from ..render.text import to_markdown
from ..runs import RunRecord, UsageDelta, write_record
from .errors import JobError, PlaylistUnsupported, classify

LOG = logging.getLogger("ytexplain.web")

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"
ACTIVE = (QUEUED, RUNNING)
MAX_JOBS = 50


@dataclass(slots=True)
class JobRequest:
    url: str
    model: str | None = None
    fast: bool = False
    markdown: bool = False
    include_transcript: bool = False
    lang: str = "en"


@dataclass(slots=True)
class Job:
    id: str
    url: str
    status: str = QUEUED
    progress: list[str] = field(default_factory=list)
    error: JobError | None = None
    pdf: Path | None = None
    record: RunRecord | None = None
    model: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def active(self) -> bool:
        return self.status in ACTIVE


class JobStore:
    """A capped dict of jobs, safe to touch from the worker and request threads.

    The cap matters because the server is meant to stay up for weeks: without it,
    every submission leaks a job and its progress lines for the life of the
    process. Finished jobs go first, oldest first, and a running job is never
    evicted — nothing else knows it exists.
    """

    def __init__(self, max_jobs: int = MAX_JOBS) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_jobs = max_jobs

    def add(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.id] = job
            self._evict()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def active_for(self, url: str) -> Job | None:
        with self._lock:
            for job in self._jobs.values():
                if job.url == url and job.active:
                    return job
        return None

    def _evict(self) -> None:
        finished = sorted(
            (job for job in self._jobs.values() if not job.active),
            key=lambda job: job.finished_at or job.created_at,
        )
        while len(self._jobs) > self._max_jobs and finished:
            del self._jobs[finished.pop(0).id]


class JobRunner:
    """Accepts submissions and runs them one at a time."""

    def __init__(self, store: JobStore | None = None) -> None:
        self.store = store or JobStore()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ytexplain-job")

    def submit(self, request: JobRequest) -> Job:
        # A second submission of the same URL would pay twice for one PDF, and the
        # two runs would race to write it. Hand back the run already in flight.
        existing = self.store.active_for(request.url)
        if existing:
            return existing
        job = self.store.add(
            Job(id=uuid.uuid4().hex[:12], url=request.url, model=request.model)
        )
        self._pool.submit(self._run, job, request)
        return job

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _run(self, job: Job, request: JobRequest) -> None:
        # Nothing may escape into the executor thread: a future nobody awaits
        # swallows its exception, and the job would sit at "running" for ever.
        job.status = RUNNING
        started = time.perf_counter()
        try:
            self._generate(job, request, started)
            job.status = DONE
        except Exception as exc:  # noqa: BLE001 - every failure becomes a job status
            job.error = classify(exc)
            job.status = FAILED
            # The traceback and any upstream response body stay here, in the log.
            LOG.exception("job %s failed (%s)", job.id, job.error.kind)
        finally:
            job.finished_at = time.time()

    def _generate(self, job: Job, request: JobRequest, started: float) -> None:
        settings = Settings.load(model=request.model)
        job.model = settings.model
        options = Options(fast=request.fast, languages=parse_languages(request.lang))
        cache = Cache(settings.cache_dir, enabled=settings.use_cache)

        job.progress.append("Resolving link")
        refs, playlist_title = collect(request.url, options)
        if len(refs) != 1:
            raise PlaylistUnsupported(
                f"That link is a playlist of {len(refs)} videos."
                " Submit a single video URL for now."
            )

        with make_client(settings, cache) as client:
            usage_before = replace(client.usage)
            document = build_document(
                refs[0],
                client=client,
                cache=cache,
                options=options,
                playlist_title=playlist_title,
                on_progress=job.progress.append,
            )
            job.progress.append("Writing PDF")
            pdf = build_pdf(
                [document],
                output_path(document, settings),
                include_transcript=request.include_transcript,
            )
            markdown_path = (
                write_atomic_text(pdf.with_suffix(".md"), to_markdown(document))
                if request.markdown
                else None
            )
            record = write_record(
                [document],
                pdf,
                usage=UsageDelta.between(usage_before, client.usage),
                seconds=time.perf_counter() - started,
                markdown_path=markdown_path,
            )

        # Set last: the UI treats a PDF path as proof the file is complete.
        job.record = record
        job.pdf = pdf
        job.progress.append(f"Done - {record.reading_time} read, {record.sections} sections")
