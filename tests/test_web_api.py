"""Web API tests. No network, no API key, no model calls.

The engine functions the worker calls are replaced with fakes, so what is under
test is the job lifecycle, the access gate and the routes -- not the pipeline,
which has its own tests.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ytexplain import config
from ytexplain.llm import Model, Usage
from ytexplain.transcript import TranscriptError
from ytexplain.web import app as app_module
from ytexplain.web import jobs as jobs_module
from ytexplain.web.jobs import Job, JobStore

TIMEOUT = 5.0


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    """Point the server at a temporary output directory and a key that is not real.

    `dotenv_path` is redirected at an absent file so a developer's own .env -- with
    a live key and their real out/ -- cannot change what these tests see.
    """
    directory = tmp_path / "out"
    directory.mkdir()
    monkeypatch.setattr(config, "dotenv_path", lambda: tmp_path / "absent.env")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("YTEXPLAIN_OUTPUT_DIR", str(directory))
    monkeypatch.setenv("YTEXPLAIN_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("YTEXPLAIN_MODEL", raising=False)
    monkeypatch.delenv("YTEXPLAIN_WEB_PASSWORD", raising=False)
    monkeypatch.setenv("YTEXPLAIN_WEB_MAX_JOBS_PER_HOUR", "10")
    return directory


@pytest.fixture
def engine(monkeypatch, make_document):
    """Stand in for the pipeline, and let a test decide how it behaves."""
    state = SimpleNamespace(
        refs=[SimpleNamespace(video_id="abc123", url="u", title="A video")],
        failure=None,
        gate=None,  # an Event a test can hold to keep a job running
        documents=1,
    )

    @contextmanager
    def fake_client(_settings, _cache):
        # The real Usage dataclass: the worker snapshots it with dataclasses.replace.
        # It starts non-zero so a worker reading the counter instead of the delta
        # would be caught.
        yield SimpleNamespace(usage=Usage(calls=99, cached_calls=5, cost_usd=1.5))

    def fake_collect(_url, _options):
        return list(state.refs), None

    def fake_build_document(_ref, *, client, cache, options, playlist_title, on_progress):
        on_progress("Fetching transcript")
        if state.gate:
            state.gate.wait(TIMEOUT)
        if state.failure:
            raise state.failure
        on_progress("Writing 2 sections")
        client.usage.calls += 7
        client.usage.cached_calls += 1
        client.usage.cost_usd += 0.02
        return make_document()

    def fake_build_pdf(documents, destination, **_kwargs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"%PDF-1.4 fake")
        return destination

    monkeypatch.setattr(jobs_module, "make_client", fake_client)
    monkeypatch.setattr(jobs_module, "collect", fake_collect)
    monkeypatch.setattr(jobs_module, "build_document", fake_build_document)
    monkeypatch.setattr(jobs_module, "build_pdf", fake_build_pdf)
    return state


@pytest.fixture
def client(out_dir, engine, monkeypatch):
    # A fresh registry and limit per test: both are process-wide by design.
    monkeypatch.setattr(app_module, "runner", jobs_module.JobRunner())
    monkeypatch.setattr(app_module, "limit", app_module.HourlyLimit())
    monkeypatch.setattr(app_module, "_models_cache", None)
    with TestClient(app_module.app) as started:
        yield started


def wait_for(client: TestClient, job_id: str, *statuses: str) -> dict:
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in statuses:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"job stayed at {payload['status']}")


def submit(client: TestClient, url: str = "https://youtu.be/abc123", **body) -> dict:
    response = client.post("/api/jobs", json={"url": url, **body})
    assert response.status_code == 202, response.text
    return response.json()


def test_a_job_runs_and_exposes_its_progress_pdf_and_record(client, out_dir):
    finished = wait_for(client, submit(client)["id"], "done")

    assert finished["progress"][0] == "Resolving link"
    assert "Fetching transcript" in finished["progress"]
    assert finished["progress"][-1].startswith("Done")
    assert finished["record"]["reading_time"] == "2 min"
    # The delta for this run, not the client's running total.
    assert (finished["record"]["cost_usd"], finished["record"]["calls"]) == (0.02, 7)
    assert finished["error"] is None

    pdf = client.get(finished["pdf_url"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"

    # The same run record the CLI writes, so history covers both entry points.
    history = client.get("/api/history").json()
    assert [entry["title"] for entry in history] == ["A video"]
    assert history[0]["file"] == "a-video.pdf"
    assert client.get(f"/api/files/{history[0]['file']}").status_code == 200


def test_a_playlist_is_refused_with_an_explanation(client, engine):
    engine.refs = [SimpleNamespace(video_id=f"v{n}", url="u", title=None) for n in range(3)]

    failed = wait_for(client, submit(client)["id"], "failed")

    assert failed["error"]["kind"] == "playlist_unsupported"
    assert "3 videos" in failed["error"]["message"]
    assert failed["error"]["retryable"] is False


def test_a_missing_transcript_fails_the_job_without_leaking_the_detail(client, engine):
    engine.failure = TranscriptError("yt-dlp said: HTTP 429 from 1.2.3.4, cookies rejected")

    failed = wait_for(client, submit(client)["id"], "failed")

    assert failed["error"]["kind"] == "no_captions"
    assert "yt-dlp" not in failed["error"]["message"]
    assert "1.2.3.4" not in failed["error"]["message"]
    # Progress up to the failure is kept: it is how someone sees where it got to.
    assert failed["progress"] == ["Resolving link", "Fetching transcript"]


def test_an_unexpected_failure_is_still_reported_as_a_failed_job(client, engine):
    engine.failure = ZeroDivisionError("bug in the renderer")

    failed = wait_for(client, submit(client)["id"], "failed")

    assert failed["error"]["kind"] == "unknown"
    assert "ZeroDivision" not in failed["error"]["message"]


def test_submitting_the_same_url_twice_reuses_the_running_job(client, engine):
    engine.gate = threading.Event()
    try:
        first = submit(client)
        second = submit(client)
        assert first["id"] == second["id"]  # one run, one bill
    finally:
        engine.gate.set()

    wait_for(client, first["id"], "done")
    assert len(client.get("/api/jobs").json()) == 1


def test_a_finished_job_does_not_block_resubmission(client):
    first = wait_for(client, submit(client)["id"], "done")
    second = submit(client)
    assert second["id"] != first["id"]


def test_unknown_jobs_are_404_which_is_what_a_restart_looks_like(client):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/jobs/nope/pdf").status_code == 404


def test_the_hourly_limit_returns_429_with_the_wait(client, monkeypatch):
    monkeypatch.setenv("YTEXPLAIN_WEB_MAX_JOBS_PER_HOUR", "1")
    submit(client)

    refused = client.post("/api/jobs", json={"url": "https://youtu.be/other"})
    assert refused.status_code == 429
    assert "Hourly limit of 1 run reached" in refused.json()["detail"]
    assert int(refused.headers["retry-after"]) > 3500


def test_a_server_without_an_api_key_says_so_on_submit(client, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")

    refused = client.post("/api/jobs", json={"url": "https://youtu.be/abc123"})
    assert refused.status_code == 503
    assert "OPENROUTER_API_KEY" in refused.json()["detail"]
    assert client.get("/api/settings").json()["has_api_key"] is False


def test_the_password_gate_guards_the_api_but_not_the_settings(client, monkeypatch):
    monkeypatch.setenv("YTEXPLAIN_WEB_PASSWORD", "letmein")

    assert client.get("/api/history").status_code == 401
    assert client.get("/api/history", headers={"X-Access-Token": "nope"}).status_code == 401
    assert client.get("/api/history", headers={"X-Access-Token": "letmein"}).status_code == 200
    assert client.post("/api/jobs", json={"url": "u"}).status_code == 401
    # The page has to be able to ask whether a password is needed.
    settings = client.get("/api/settings")
    assert settings.status_code == 200
    assert settings.json()["requires_password"] is True


def test_no_password_set_means_no_gate(client):
    assert client.get("/api/history").status_code == 200
    assert client.get("/api/settings").json()["requires_password"] is False


@pytest.mark.parametrize(
    "name",
    [
        "../secret.txt",
        "..%2Fsecret.txt",
        "%2e%2e%2fsecret.txt",
        "nested/../../secret.txt",
    ],
)
def test_files_cannot_escape_the_output_directory(client, out_dir, name):
    (out_dir.parent / "secret.txt").write_text("OPENROUTER_API_KEY=real", encoding="utf-8")

    response = client.get(f"/api/files/{name}")

    assert response.status_code == 404
    assert "real" not in response.text


def test_files_only_serves_documents(client, out_dir):
    (out_dir / "a-video.pdf").write_bytes(b"%PDF-1.4")
    (out_dir / "a-video.md").write_text("# A video", encoding="utf-8")
    (out_dir / "a-video.json").write_text('{"cost_usd": 0.02}', encoding="utf-8")

    assert client.get("/api/files/a-video.pdf").status_code == 200
    assert client.get("/api/files/a-video.md").status_code == 200
    # Records reach the page through /api/history, already shaped for it.
    assert client.get("/api/files/a-video.json").status_code == 404


def test_the_model_catalogue_is_fetched_once_an_hour(client, monkeypatch):
    calls = []

    def fake_list_models():
        calls.append(1)
        return [Model(id="a/b", name="A B", context=8192, prompt_usd=1.0, completion_usd=2.0)]

    monkeypatch.setattr(app_module, "list_models", fake_list_models)

    first = client.get("/api/models").json()
    client.get("/api/models")

    assert first == [{"id": "a/b", "name": "A B", "context": 8192, "prompt_usd": 1.0, "completion_usd": 2.0}]
    assert len(calls) == 1


def test_history_survives_an_unreadable_record(client, out_dir):
    (out_dir / "broken.json").write_text("{ not json", encoding="utf-8")
    wait_for(client, submit(client)["id"], "done")

    assert [entry["title"] for entry in client.get("/api/history").json()] == ["A video"]


def test_the_registry_evicts_finished_jobs_but_never_a_running_one():
    store = JobStore(max_jobs=2)
    running = store.add(Job(id="running", url="u"))
    for index in range(3):
        job = store.add(Job(id=f"done{index}", url=f"u{index}"))
        job.status = "done"
        job.finished_at = 100 + index

    kept = {job.id for job in store.all()}
    assert running.id in kept
    assert "done0" not in kept  # oldest finished job went first
    assert len(kept) <= 3  # the running job is over the cap, not evicted by it
