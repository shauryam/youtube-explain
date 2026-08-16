"""Serialise an explainer back to Markdown, for reuse outside the PDF."""

from __future__ import annotations

from ..models import Document, format_reading_time, format_timestamp


def to_markdown(document: Document) -> str:
    explainer, meta = document.explainer, document.meta
    lines = [f"# {explainer.title}", ""]

    facts = [f"**Source:** [{meta.title}]({meta.url})"]
    if meta.channel:
        facts.append(f"**Channel:** {meta.channel}")
    duration = meta.duration or document.transcript.duration
    if duration:
        facts.append(f"**Length:** {format_timestamp(duration)}")
    facts.append(f"**Reading time:** {format_reading_time(explainer.words)}")
    if explainer.translated:
        facts.append(f"**Translated from:** {explainer.source_language}")
    lines += [" · ".join(facts), ""]

    if explainer.abstract:
        lines += ["> " + explainer.abstract, ""]
    if explainer.prerequisites:
        lines += ["## Before you start", ""]
        lines += [f"- {item}" for item in explainer.prerequisites] + [""]

    for index, section in enumerate(explainer.sections, start=1):
        lines += [f"## {index}. {section.heading}", "", section.body.strip(), ""]

    if explainer.key_terms:
        lines += ["## Glossary", ""]
        lines += [f"- **{term}** — {definition}" for term, definition in explainer.key_terms] + [""]
    if explainer.takeaways:
        lines += ["## Key takeaways", ""]
        lines += [f"- {item}" for item in explainer.takeaways] + [""]

    return "\n".join(lines)
