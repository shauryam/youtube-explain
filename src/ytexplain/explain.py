"""Turn a transcript into a structured, comprehensive explainer.

Two passes, because one pass cannot do both jobs well: a planning pass reads the
whole transcript and decides the document's shape, then an expansion pass writes
each section from just that section's slice of the transcript. Splitting the work
keeps every section within a comfortable output-token budget, which is what makes
the result an explanation rather than a summary.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import prompts
from .llm import LLMError, OpenRouterClient
from .models import Explainer, Section, Transcript, VideoMeta, format_timestamp

OUTLINE_CHAR_LIMIT = 600_000
MIN_SLICE_CHARS = 500
SLICE_PADDING = 45.0
TIMESTAMP = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})")

ProgressHook = Callable[[str], None]


def build_explainer(
    transcript: Transcript,
    meta: VideoMeta,
    client: OpenRouterClient,
    *,
    fast: bool = False,
    concurrency: int = 4,
    on_progress: ProgressHook | None = None,
) -> Explainer:
    notify = on_progress or (lambda _message: None)
    rules = _rules(transcript)

    notify("Planning document structure")
    outline = _outline(transcript, meta, client, rules)
    explainer = _explainer_from_outline(outline, transcript, meta, client.model)
    if not explainer.sections:
        raise ValueError("The model returned no sections for this video")

    wrote_in_one_pass = False
    if fast:
        notify(f"Writing {len(explainer.sections)} sections in one pass")
        wrote_in_one_pass = _expand_together(explainer, transcript, meta, client, rules)
        if not wrote_in_one_pass:
            notify("One-pass write failed, falling back to per-section writing")
    if not wrote_in_one_pass:
        _expand_each(explainer, transcript, client, rules, concurrency, notify)

    explainer.sections = [s for s in explainer.sections if s.body.strip()]
    if not explainer.sections:
        raise ValueError("The model returned no section content for this video")
    return explainer


def _rules(transcript: Transcript) -> str:
    parts = [prompts.BASE_RULE]
    if not transcript.is_english:
        parts.append(prompts.TRANSLATION_RULE)
    if transcript.is_generated:
        parts.append(prompts.CAPTION_RULE)
    return "\n\n".join(parts)


def _transcript_for_outline(transcript: Transcript) -> str:
    text = transcript.timestamped_text()
    if len(text) <= OUTLINE_CHAR_LIMIT:
        return text
    half = OUTLINE_CHAR_LIMIT // 2
    return f"{text[:half]}\n\n[... middle of transcript omitted for length ...]\n\n{text[-half:]}"


def _outline_user_prompt(transcript: Transcript, meta: VideoMeta) -> str:
    return prompts.OUTLINE_USER.format(
        title=meta.title,
        channel=meta.channel or "unknown",
        duration=format_timestamp(meta.duration or transcript.duration),
        language=transcript.language_code,
        caption_kind="auto-generated" if transcript.is_generated else "human-written",
        transcript=_transcript_for_outline(transcript),
    )


def _outline(transcript: Transcript, meta: VideoMeta, client: OpenRouterClient, rules: str) -> dict:
    return client.complete_json(
        system=prompts.OUTLINE_SYSTEM.format(rules=rules),
        user=_outline_user_prompt(transcript, meta),
        require_key="sections",
        temperature=0.2,
        max_tokens=8000,
    )


def _explainer_from_outline(
    outline: dict, transcript: Transcript, meta: VideoMeta, model: str
) -> Explainer:
    sections = []
    for raw in outline.get("sections") or []:
        heading = str(raw.get("heading") or "").strip()
        if not heading:
            continue
        sections.append(
            Section(
                heading=heading,
                focus=str(raw.get("focus") or "").strip(),
                start=_seconds(raw.get("start")),
                end=_seconds(raw.get("end")) or transcript.duration,
            )
        )

    return Explainer(
        title=str(outline.get("title") or meta.title).strip(),
        abstract=str(outline.get("abstract") or "").strip(),
        prerequisites=_strings(outline.get("prerequisites")),
        sections=sections,
        key_terms=_terms(outline.get("key_terms")),
        takeaways=_strings(outline.get("takeaways")),
        source_language=str(outline.get("source_language") or transcript.language_code),
        translated=not transcript.is_english,
        model=model,
    )


def _expand_each(
    explainer: Explainer,
    transcript: Transcript,
    client: OpenRouterClient,
    rules: str,
    concurrency: int,
    notify: ProgressHook,
) -> None:
    system = prompts.SECTION_SYSTEM.format(rules=rules)
    total = len(explainer.sections)

    def write(index: int) -> str:
        section = explainer.sections[index]
        user = prompts.SECTION_USER.format(
            title=explainer.title,
            abstract=explainer.abstract,
            outline=_outline_listing(explainer, highlight=index),
            heading=section.heading,
            focus=section.focus,
            start=format_timestamp(section.start),
            end=format_timestamp(section.end),
            transcript=_slice_for(transcript, section),
        )
        return client.complete(system=system, user=user, temperature=0.35)

    notify(f"Writing {total} sections")
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(write, index): index for index in range(total)}
        for done, future in enumerate(as_completed(futures), start=1):
            index = futures[future]
            explainer.sections[index].body = future.result().strip()
            notify(f"Section {done}/{total}: {explainer.sections[index].heading}")


def _expand_together(
    explainer: Explainer,
    transcript: Transcript,
    meta: VideoMeta,
    client: OpenRouterClient,
    rules: str,
) -> bool:
    """Write every section in one call. Returns False if the call was unusable."""
    try:
        payload = client.complete_json(
            system=prompts.FAST_SYSTEM.format(rules=rules),
            user=prompts.FAST_USER.format(
                title=meta.title,
                channel=meta.channel or "unknown",
                duration=format_timestamp(meta.duration or transcript.duration),
                language=transcript.language_code,
                caption_kind="auto-generated" if transcript.is_generated else "human-written",
                transcript=_transcript_for_outline(transcript),
                outline=_outline_listing(explainer),
            ),
            require_key="sections",
            temperature=0.35,
            max_tokens=60000,
        )
    except LLMError:
        return False

    bodies = {
        str(item.get("heading") or "").strip().lower(): str(item.get("body") or "")
        for item in payload.get("sections") or []
    }
    written = list(bodies.values())
    for index, section in enumerate(explainer.sections):
        body = bodies.get(section.heading.lower())
        if body is None and index < len(written):
            body = written[index]
        section.body = (body or "").strip()
    return any(section.body for section in explainer.sections)


def _outline_listing(explainer: Explainer, highlight: int | None = None) -> str:
    lines = []
    for index, section in enumerate(explainer.sections):
        marker = ">>>" if index == highlight else f"{index + 1}."
        lines.append(f"{marker} {section.heading} - {section.focus}")
    return "\n".join(lines)


def _slice_for(transcript: Transcript, section: Section) -> str:
    text = transcript.slice_text(section.start, section.end, padding=SLICE_PADDING)
    return text if len(text) >= MIN_SLICE_CHARS else transcript.timestamped_text()


def _seconds(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return 0.0
    if match := TIMESTAMP.search(str(value)):
        hours, minutes, secs = match.groups()
        return int(hours or 0) * 3600 + int(minutes) * 60 + int(secs)
    try:
        return float(str(value).strip())
    except ValueError:
        return 0.0


def _strings(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _terms(value) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []
    terms = []
    for item in value:
        if isinstance(item, dict):
            term = str(item.get("term") or "").strip()
            definition = str(item.get("definition") or "").strip()
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            term, definition = (str(part).strip() for part in item)
        else:
            continue
        if term:
            terms.append((term, definition))
    return terms
