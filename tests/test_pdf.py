from reportlab.platypus import Paragraph

from ytexplain.models import Document
from ytexplain.render.pdf import _chapter_meta, _cover, build_styles


def cover_text(documents: list[Document], *, multi: bool) -> str:
    story = _cover(documents, build_styles(), "T", multi)
    return " ".join(flow.text for flow in story if isinstance(flow, Paragraph))


def test_cover_states_the_reading_time(make_document):
    assert "2 min read" in cover_text([make_document()], multi=False)


def test_combined_cover_sums_the_chapters(make_document):
    assert "4 min read" in cover_text([make_document(), make_document()], multi=True)


def test_chapter_meta_states_the_reading_time(make_document):
    assert "2 min read" in _chapter_meta(make_document())
