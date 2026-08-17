"""The HTTP surface. Presentation only: no engine logic lives here.

Progress reaches the browser by polling rather than server-sent events. A run
produces a dozen or so progress lines over a minute and a half, so a one-second
poll is indistinguishable from a push, and it avoids the parts of SSE that are
genuinely awkward: proxies that buffer the stream, connections dropped by idle
timeouts, and reconnect logic that has to work out what was missed.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import ConfigError, Settings
from ..llm import LLMError, list_models
from ..runs import load_records
from .jobs import Job, JobRequest, JobRunner

PASSWORD_VAR = "YTEXPLAIN_WEB_PASSWORD"
LIMIT_VAR = "YTEXPLAIN_WEB_MAX_JOBS_PER_HOUR"
DEFAULT_LIMIT = 10
MODELS_TTL = 3600.0
SERVED_SUFFIXES = frozenset({".pdf", ".md"})
# The built frontend sits beside the repo's src/ in development; a deployment that
# puts it elsewhere sets the variable rather than moving the package around.
FRONTEND = Path(
    os.environ.get("YTEXPLAIN_WEB_DIST")
    or Path(__file__).resolve().parents[3] / "web" / "dist"
)

runner = JobRunner()


class JobBody(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    model: str | None = None
    fast: bool = False
    markdown: bool = False
    include_transcript: bool = False
    lang: str = "en"


class HourlyLimit:
    """A rolling hourly cap on submissions, held in memory like the jobs are.

    It exists to bound spend on a key that is shared with whoever has the
    password, not to defend against a determined attacker: a restart clears it.
    Durable throttling needs durable storage, which is a trade for later.
    """

    def __init__(self) -> None:
        self._starts: deque[float] = deque()
        self._lock = threading.Lock()

    @staticmethod
    def maximum() -> int:
        try:
            return max(0, int(os.environ.get(LIMIT_VAR, DEFAULT_LIMIT)))
        except ValueError:
            return DEFAULT_LIMIT

    def take(self) -> float | None:
        """Record a submission, or return the seconds until one is allowed."""
        maximum = self.maximum()
        now = time.time()
        with self._lock:
            while self._starts and now - self._starts[0] >= 3600:
                self._starts.popleft()
            if len(self._starts) >= maximum:
                return round(3600 - (now - self._starts[0]), 1)
            self._starts.append(now)
        return None


limit = HourlyLimit()


def require_access(
    x_access_token: Annotated[str | None, Header()] = None,
) -> None:
    """Check the shared password, if one is set.

    Read from the environment per request rather than at import, so a test or a
    restart-free config change takes effect, and skipped entirely when unset so
    local development needs no setup.
    """
    password = os.environ.get(PASSWORD_VAR)
    if not password:
        return
    if not x_access_token or not secrets.compare_digest(x_access_token, password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong or missing access token")


def job_payload(job: Job) -> dict:
    return {
        "id": job.id,
        "url": job.url,
        "status": job.status,
        "model": job.model,
        "progress": list(job.progress),
        "error": asdict(job.error) if job.error else None,
        "pdf_url": f"/api/jobs/{job.id}/pdf" if job.pdf else None,
        "record": asdict(job.record) if job.record else None,
        "created_at": job.created_at,
    }


app = FastAPI(title="ytexplain", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.get("/api/settings")
def read_settings() -> dict:
    """Everything the page needs before it can ask for anything else."""
    settings = Settings.load()
    return {
        "default_model": settings.model,
        "requires_password": bool(os.environ.get(PASSWORD_VAR)),
        "max_jobs_per_hour": HourlyLimit.maximum(),
        "has_api_key": bool(settings.api_key),
    }


@app.post("/api/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_job(body: JobBody, _: None = Depends(require_access)) -> dict:
    try:
        Settings.load(model=body.model).require_api_key()
    except ConfigError as exc:
        # The server is misconfigured, so this is not a failure of the request.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    retry_after = limit.take()
    if retry_after is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Hourly limit of {HourlyLimit.maximum()} runs reached.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    job = runner.submit(JobRequest(**body.model_dump()))
    return job_payload(job)


@app.get("/api/jobs")
def list_jobs(_: None = Depends(require_access)) -> list[dict]:
    return [job_payload(job) for job in runner.store.all()]


@app.get("/api/jobs/{job_id}")
def read_job(job_id: str, _: None = Depends(require_access)) -> dict:
    job = runner.store.get(job_id)
    if not job:
        # Also what a restart looks like from the outside; the UI offers to resubmit.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job")
    return job_payload(job)


@app.get("/api/jobs/{job_id}/pdf")
def read_job_pdf(job_id: str, _: None = Depends(require_access)) -> FileResponse:
    job = runner.store.get(job_id)
    if not job or not job.pdf or not job.pdf.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No PDF for this job")
    return FileResponse(job.pdf, media_type="application/pdf", filename=job.pdf.name)


@app.get("/api/history")
def read_history(_: None = Depends(require_access)) -> list[dict]:
    out_dir = Settings.load().output_dir
    return [
        asdict(record) | {"file": path.relative_to(out_dir).as_posix()}
        for record, path in load_records(out_dir)
    ]


@app.get("/api/files/{name:path}")
def read_file(name: str, _: None = Depends(require_access)) -> FileResponse:
    """Serve a file from the output directory by name, for the history list."""
    root = Settings.load().output_dir.resolve()
    target = (root / name).resolve()
    # Resolve first, then check containment: without this, "../../.env" would be
    # a valid name. The suffix check keeps run records out of the served set.
    if (
        not target.is_relative_to(root)
        or target.suffix not in SERVED_SUFFIXES
        or not target.is_file()
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such file")
    media_type = "application/pdf" if target.suffix == ".pdf" else "text/markdown"
    return FileResponse(target, media_type=media_type, filename=target.name)


_models_cache: tuple[float, list[dict]] | None = None


@app.get("/api/models")
def read_models(_: None = Depends(require_access)) -> list[dict]:
    """OpenRouter's catalogue, cached for an hour: it changes weekly at most."""
    global _models_cache
    if _models_cache and time.monotonic() - _models_cache[0] < MODELS_TTL:
        return _models_cache[1]
    try:
        models = [asdict(model) for model in list_models()]
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    _models_cache = (time.monotonic(), models)
    return models


if FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
else:

    @app.get("/", response_class=PlainTextResponse)
    def missing_frontend() -> str:
        # A bare 404 here reads as a broken server rather than an unbuilt one.
        return (
            "The API is running, but the built frontend is missing.\n"
            f"Expected it at {FRONTEND}.\n\n"
            "Run `npm install && npm run build` in web/, or use `npm run dev`"
            " on port 5173 while developing.\n"
        )
