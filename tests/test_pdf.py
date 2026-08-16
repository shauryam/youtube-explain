from reportlab.platypus import Paragraph

from ytexplain.models import (
    Document,
    Explainer,
    Section,
    Segment,
    Transcript,
    VideoMeta,
)
from ytexplain.render.pdf import _chapter_meta, _cover, build_styles


def document(words: int = 400) -> Document:
    return Document(
        meta=VideoMeta(
            video_id="x",
            url="https://example.com",
            title="T",
            channel="C",
            duration=600,
        ),
        explainer=Explainer(title="T", sections=[Section(heading="h", body="word " * words)]),
        transcript=Transcript(
            segments=[Segment(start=0.0, duration=5.0, text="cue")],
            language_code="en",
            is_generated=False,
            source="test",
        ),
    )


def cover_text(documents: list[Document], *, multi: bool) -> str:
    story = _cover(documents, build_styles(), "T", multi)
    return " ".join(flow.text for flow in story if isinstance(flow, Paragraph))


def test_cover_states_the_reading_time():
    assert "2 min read" in cover_text([document()], multi=False)


def test_combined_cover_sums_the_chapters():
    assert "4 min read" in cover_text([document(), document()], multi=True)


def test_chapter_meta_states_the_reading_time():
    assert "2 min read" in _chapter_meta(document())
