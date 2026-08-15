import json

import pytest

from ytexplain.explain import _rules, _seconds, _terms
from ytexplain.llm import JSON_FENCE, _loads
from ytexplain.models import Segment, Transcript
from ytexplain.pipeline import slugify


def transcript(text: str, language: str = "en", generated: bool = False) -> Transcript:
    return Transcript(
        segments=[Segment(start=float(i * 5), duration=5.0, text=part)
                  for i, part in enumerate(text.split("|"))],
        language_code=language,
        is_generated=generated,
        source="test",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1:30", 90), ("1:02:03", 3723), ("0:00", 0), (42, 42), ("42", 42), (None, 0), ("junk", 0)],
)
def test_seconds_parsing(value, expected):
    assert _seconds(value) == expected


def test_hindi_transcript_gets_translation_rule():
    hindi = transcript("यह हिंदी है", language="hi", generated=True)
    assert hindi.script == "devanagari"
    assert not hindi.is_english
    rules = _rules(hindi)
    assert "write everything you output in clear, natural English" in rules
    assert "machine-generated captions" in rules


def test_english_human_captions_get_only_the_base_rule():
    rules = _rules(transcript("plain english"))
    assert "not in English" not in rules
    assert "machine-generated captions" not in rules
    assert "idiomatic written English" in rules


def test_blocks_merge_into_windows_and_slice_by_time():
    t = transcript("|".join(f"cue{i}" for i in range(20)))
    assert len(t.blocks(window=30.0)) < len(t.segments)
    sliced = t.slice_text(0, 10, padding=0)
    assert "cue0" in sliced and "cue19" not in sliced


def test_terms_accepts_dicts_and_pairs():
    assert _terms([{"term": "a", "definition": "b"}]) == [("a", "b")]
    assert _terms([["a", "b"]]) == [("a", "b")]
    assert _terms(["nope", None]) == []


def test_loads_tolerates_literal_newlines_in_strings():
    raw = '```json\n{"sections": [{"heading": "h", "body": "line one\nline two"}]}\n```'
    with pytest.raises(json.JSONDecodeError):
        json.loads(JSON_FENCE.sub("", raw))
    payload = _loads(JSON_FENCE.sub("", raw))
    assert payload["sections"][0]["body"] == "line one\nline two"


@pytest.mark.parametrize(
    ("title", "expected"),
    [("Hello, World!", "hello-world"), ("  ", "untitled"), ("A/B: test", "a-b-test")],
)
def test_slugify(title, expected):
    assert slugify(title) == expected
