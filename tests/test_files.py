import pytest

from ytexplain import render
from ytexplain.cache import Cache
from ytexplain.files import atomic_path, write_atomic_text


def temp_leftovers(directory):
    return sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))


def test_atomic_path_publishes_only_on_success(tmp_path):
    target = tmp_path / "nested" / "out.txt"
    with atomic_path(target) as temp:
        temp.write_text("finished", encoding="utf-8")
        assert not target.exists()  # invisible until the block ends

    assert target.read_text(encoding="utf-8") == "finished"
    assert temp_leftovers(target.parent) == []


def test_atomic_path_leaves_the_previous_file_alone_when_writing_fails(tmp_path):
    target = tmp_path / "out.txt"
    target.write_text("original", encoding="utf-8")

    with pytest.raises(RuntimeError):
        with atomic_path(target) as temp:
            temp.write_text("half a file", encoding="utf-8")
            raise RuntimeError("render blew up")

    assert target.read_text(encoding="utf-8") == "original"
    assert temp_leftovers(tmp_path) == []


def test_write_atomic_text_creates_missing_directories(tmp_path):
    written = write_atomic_text(tmp_path / "a" / "b" / "note.md", "hello")
    assert written.read_text(encoding="utf-8") == "hello"


def test_published_file_has_ordinary_permissions(tmp_path):
    # Compared against a plain write so the assertion holds under any umask.
    plain = tmp_path / "plain.txt"
    plain.write_text("x", encoding="utf-8")
    atomic = write_atomic_text(tmp_path / "atomic.txt", "x")
    assert atomic.stat().st_mode & 0o777 == plain.stat().st_mode & 0o777


def test_cache_writes_survive_a_reread(tmp_path):
    cache = Cache(tmp_path)
    cache.set("completions", "abc", {"text": "cached"})
    assert cache.get("completions", "abc") == {"text": "cached"}
    assert temp_leftovers(tmp_path / "completions") == []


def test_failed_pdf_render_leaves_nothing_at_the_destination(tmp_path, monkeypatch):
    class ExplodingTemplate:
        def __init__(self, *args, **kwargs):
            pass

        def multiBuild(self, story):
            raise RuntimeError("layout did not converge")

    monkeypatch.setattr(render.pdf, "NotesDocTemplate", ExplodingTemplate)
    destination = tmp_path / "explainer.pdf"

    with pytest.raises(RuntimeError):
        render.build_pdf([render_document()], destination)

    assert not destination.exists()
    assert temp_leftovers(tmp_path) == []


def render_document():
    from ytexplain.models import Document, Explainer, Section, Transcript, VideoMeta

    return Document(
        meta=VideoMeta(video_id="v", url="https://example.com/v", title="A video"),
        explainer=Explainer(title="A video", sections=[Section(heading="One", body="Body")]),
        transcript=Transcript(segments=[], language_code="en", is_generated=False, source="test"),
    )
