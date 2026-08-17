import json
from types import SimpleNamespace

from ytexplain.models import Document, Explainer, Section, Transcript, VideoMeta
from ytexplain.runs import UsageDelta, load_records, record_path, write_record


def document(video_id="abc123", title="A video", words=400, sections=2, channel="A channel"):
    body = " ".join(["word"] * (words // max(1, sections)))
    return Document(
        meta=VideoMeta(
            video_id=video_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
            title=title,
            channel=channel,
        ),
        explainer=Explainer(
            title=title,
            model="z-ai/glm-5.2",
            sections=[Section(heading=f"Part {n}", body=body) for n in range(sections)],
        ),
        transcript=Transcript(
            segments=[], language_code="en", is_generated=False, source="test"
        ),
    )


def usage(cost=0.0, calls=0, cached=0):
    return SimpleNamespace(cost_usd=cost, calls=calls, cached_calls=cached)


def test_usage_delta_measures_one_document_out_of_running_totals():
    delta = UsageDelta.between(usage(cost=0.5, calls=9), usage(cost=0.53, calls=16, cached=2))
    assert (delta.cost_usd, delta.calls, delta.cached_calls) == (0.03, 7, 2)


def test_write_record_lands_beside_the_pdf(tmp_path):
    pdf = tmp_path / "a-video.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    record = write_record(
        [document()], pdf, usage=UsageDelta(cost_usd=0.02, calls=7), seconds=84.42
    )

    assert record.title == "A video"
    assert record_path(pdf) == tmp_path / "a-video.json"
    payload = json.loads(record_path(pdf).read_text(encoding="utf-8"))
    assert payload["pdf"] == "a-video.pdf"  # filename only, so the pair can move together
    assert payload["url"] == "https://www.youtube.com/watch?v=abc123"
    assert payload["model"] == "z-ai/glm-5.2"
    assert (payload["sections"], payload["videos"], payload["cost_usd"]) == (2, 1, 0.02)
    assert payload["seconds"] == 84.4
    assert payload["reading_time"] == "2 min"
    assert payload["generated_at"].endswith("+00:00")


def test_write_record_for_a_combined_book_covers_every_video(tmp_path):
    pdf = tmp_path / "playlist.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    write_record(
        [document(video_id="one"), document(video_id="two")],
        pdf,
        usage=UsageDelta(cost_usd=0.1, calls=14),
        seconds=200,
        title="A playlist",
        url="https://www.youtube.com/playlist?list=PL1",
    )

    payload = json.loads(record_path(pdf).read_text(encoding="utf-8"))
    assert payload["title"] == "A playlist"
    assert payload["url"] == "https://www.youtube.com/playlist?list=PL1"
    assert (payload["videos"], payload["sections"]) == (2, 4)
    # No single video or channel owns a combined book.
    assert (payload["video_id"], payload["channel"]) == ("", None)


def test_load_records_returns_newest_first_with_its_pdf(tmp_path):
    for name, video in (("old", "v1"), ("new", "v2")):
        pdf = tmp_path / f"{name}.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        write_record([document(video_id=video)], pdf, usage=UsageDelta(), seconds=1)
        payload = json.loads(record_path(pdf).read_text(encoding="utf-8"))
        payload["generated_at"] = "2026-01-01T00:00:00+00:00" if name == "old" else "2026-06-01T00:00:00+00:00"
        record_path(pdf).write_text(json.dumps(payload), encoding="utf-8")

    found = load_records(tmp_path)
    assert [record.video_id for record, _ in found] == ["v2", "v1"]
    assert [path.name for _, path in found] == ["new.pdf", "old.pdf"]


def test_load_records_finds_playlist_subfolders(tmp_path):
    folder = tmp_path / "a-playlist"
    folder.mkdir()
    pdf = folder / "01-first.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    write_record([document()], pdf, usage=UsageDelta(), seconds=1)

    found = load_records(tmp_path)
    assert [path.relative_to(tmp_path).as_posix() for _, path in found] == [
        "a-playlist/01-first.pdf"
    ]


def test_load_records_skips_orphans_and_junk(tmp_path):
    orphan = tmp_path / "deleted.pdf"
    orphan.write_bytes(b"%PDF-1.4")
    write_record([document()], orphan, usage=UsageDelta(), seconds=1)
    orphan.unlink()  # PDF cleared out, record left behind

    (tmp_path / "not-a-record.json").write_text("{ this is not json", encoding="utf-8")
    (tmp_path / "unrelated.json").write_text('{"hello": "world"}', encoding="utf-8")

    assert load_records(tmp_path) == []
