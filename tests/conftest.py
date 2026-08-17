"""Fixtures shared across the suite.

The document factory lives here because several modules need a `Document` and
were each growing their own slightly different builder, which is how tests end up
disagreeing about what a realistic document looks like.
"""

from __future__ import annotations

import pytest

from ytexplain.models import (
    Document,
    Explainer,
    Section,
    Segment,
    Transcript,
    VideoMeta,
)


@pytest.fixture
def make_document():
    def build(
        *,
        video_id: str = "abc123",
        title: str = "A video",
        words: int = 400,
        sections: int = 2,
        channel: str | None = "A channel",
        duration: int | None = 600,
        model: str = "z-ai/glm-5.2",
    ) -> Document:
        # Words are spread evenly, so `words` stays a fair description of the
        # whole document rather than of one section.
        body = "word " * max(1, words // max(1, sections))
        return Document(
            meta=VideoMeta(
                video_id=video_id,
                url=f"https://www.youtube.com/watch?v={video_id}",
                title=title,
                channel=channel,
                duration=duration,
            ),
            explainer=Explainer(
                title=title,
                model=model,
                sections=[
                    Section(heading=f"Part {index + 1}", body=body)
                    for index in range(sections)
                ],
            ),
            transcript=Transcript(
                segments=[Segment(start=0.0, duration=5.0, text="cue")],
                language_code="en",
                is_generated=False,
                source="test",
            ),
        )

    return build
