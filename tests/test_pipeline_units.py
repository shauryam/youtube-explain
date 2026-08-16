import json
from types import SimpleNamespace

import pytest

from ytexplain import config
from ytexplain.cli import matching_models
from ytexplain.config import DEFAULT_MODEL, Settings
from ytexplain.explain import _rules, _seconds, _terms
from ytexplain.llm import JSON_FENCE, _loads, _models_from_payload
from ytexplain.models import (
    Document,
    Explainer,
    Section,
    Segment,
    Transcript,
    VideoMeta,
    format_reading_time,
)
from ytexplain.pipeline import slugify
from ytexplain.render.text import to_markdown
from ytexplain.transcript import TranscriptError, _choose_track, _choose_ytdlp_track


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


def track(code: str, generated: bool = False):
    return SimpleNamespace(language_code=code, is_generated=generated)


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        ([track("en-GB"), track("hi")], ("en-GB", False)),
        ([track("en", generated=True), track("en")], ("en", False)),
        ([track("de"), track("en", generated=True)], ("en", True)),
        ([track("en-GB"), track("en")], ("en", False)),
        ([track("de", generated=True), track("fr")], ("fr", False)),
    ],
)
def test_choose_track_follows_the_preference_ladder(available, expected):
    chosen = _choose_track(available, ("en",))
    assert (chosen.language_code, chosen.is_generated) == expected


def test_choose_track_without_captions_raises():
    with pytest.raises(TranscriptError):
        _choose_track([], ("en",))


@pytest.mark.parametrize(
    ("manual", "auto", "expected"),
    [
        ({"en-IN": []}, {"en": []}, ("en-IN", False)),
        ({"de": []}, {"en": []}, ("en", True)),
        ({}, {"hi": [], "en": []}, ("en", True)),
    ],
)
def test_choose_ytdlp_track_ranks_pools_together(manual, auto, expected):
    code, _tracks, generated = _choose_ytdlp_track(manual, auto, ("en",))
    assert (code, generated) == expected


def test_choose_ytdlp_track_without_captions_raises():
    with pytest.raises(TranscriptError):
        _choose_ytdlp_track({}, {}, ("en",))


@pytest.mark.parametrize(
    ("words", "expected"),
    [(0, "1 min"), (150, "1 min"), (2000, "10 min"), (12_000, "1 h"), (12_200, "1 h 1 min")],
)
def test_format_reading_time(words, expected):
    assert format_reading_time(words) == expected


def test_explainer_words_counts_everything_but_the_title():
    explainer = Explainer(
        title="ignored words here",
        abstract="two words",
        prerequisites=["one"],
        sections=[Section(heading="head", body="body text here")],
        key_terms=[("term", "its definition")],
        takeaways=["final point"],
    )
    assert explainer.words == 12


CATALOGUE = {
    "data": [
        {
            "id": "z-ai/glm-5.2",
            "name": "GLM 5.2",
            "context_length": 1_048_576,
            "pricing": {"prompt": "0.00000031", "completion": "0.00000097"},
        },
        {
            "id": "anthropic/claude-sonnet-5",
            "name": "Claude Sonnet 5",
            "context_length": "200000",
        },
        {"name": "an entry with no id at all"},
    ]
}


def test_models_from_payload_converts_prices_to_per_million():
    glm = _models_from_payload(CATALOGUE)[0]
    assert glm.id == "z-ai/glm-5.2"
    assert (round(glm.prompt_usd, 2), round(glm.completion_usd, 2)) == (0.31, 0.97)
    assert glm.context == 1_048_576


def test_models_from_payload_tolerates_missing_fields():
    models = _models_from_payload(CATALOGUE)
    # Catalogue order is preserved; the entry without an id is dropped.
    assert [model.id for model in models] == ["z-ai/glm-5.2", "anthropic/claude-sonnet-5"]
    sonnet = models[1]
    assert sonnet.context == 200_000  # arrived as a string
    assert sonnet.prompt_usd == 0.0  # no pricing block at all
    assert _models_from_payload({}) == []


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("glm", ["z-ai/glm-5.2"]),
        ("GLM", ["z-ai/glm-5.2"]),
        ("sonnet", ["anthropic/claude-sonnet-5"]),
        ("  z-ai  ", ["z-ai/glm-5.2"]),
        ("", ["anthropic/claude-sonnet-5", "z-ai/glm-5.2"]),
        ("nothing here", []),
    ],
)
def test_matching_models_searches_slug_and_name(query, expected):
    assert [m.id for m in matching_models(_models_from_payload(CATALOGUE), query)] == expected


@pytest.fixture
def no_dotenv(monkeypatch):
    """Keep Settings.load away from the developer's own .env, which sets a model."""
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("YTEXPLAIN_MODEL", raising=False)


def test_settings_marks_the_fallback_model_as_unconfigured(no_dotenv):
    settings = Settings.load()
    assert (settings.model, settings.model_configured) == (DEFAULT_MODEL, False)


def test_settings_marks_env_and_flag_models_as_configured(no_dotenv, monkeypatch):
    monkeypatch.setenv("YTEXPLAIN_MODEL", "vendor/from-env")
    from_env = Settings.load()
    assert (from_env.model, from_env.model_configured) == ("vendor/from-env", True)

    from_flag = Settings.load(model="vendor/from-flag")
    assert (from_flag.model, from_flag.model_configured) == ("vendor/from-flag", True)


def test_remember_model_replaces_the_line_and_spares_the_key(no_dotenv, tmp_path):
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=sk-or-v1-secret\nYTEXPLAIN_OUTPUT_DIR=out\n")

    Settings.load(model="vendor/first").remember_model(env)
    Settings.load(model="vendor/second").remember_model(env)

    written = env.read_text()
    assert [line for line in written.splitlines() if line.startswith("YTEXPLAIN_MODEL")] == [
        "YTEXPLAIN_MODEL=vendor/second"
    ]
    assert "OPENROUTER_API_KEY=sk-or-v1-secret" in written
    assert "YTEXPLAIN_OUTPUT_DIR=out" in written


def test_dotenv_path_follows_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert config.dotenv_path().resolve() == (tmp_path / ".env").resolve()

    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=x\n")
    nested = tmp_path / "videos"
    nested.mkdir()
    monkeypatch.chdir(nested)
    # Found by walking up, so running from a subdirectory still sees the project's .env.
    assert config.dotenv_path().resolve() == (tmp_path / ".env").resolve()


def test_remember_model_creates_env_when_there_is_none(no_dotenv, tmp_path):
    env = tmp_path / ".env"
    Settings.load(model="vendor/only").remember_model(env)
    assert env.read_text().strip() == "YTEXPLAIN_MODEL=vendor/only"


def test_markdown_header_reports_reading_time():
    document = Document(
        meta=VideoMeta(video_id="x", url="https://example.com", title="T"),
        explainer=Explainer(title="T", sections=[Section(heading="h", body="word " * 400)]),
        transcript=transcript("cue"),
    )
    assert "**Reading time:** 2 min" in to_markdown(document)
