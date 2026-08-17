"""Assemble explainers into a styled PDF with a cover, contents and bookmarks."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    HRFlowable,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from ..files import atomic_path
from ..models import Document, Transcript, format_reading_time, format_timestamp
from .markdown import MarkdownRenderer, escape, inline

PAGE = A4
MARGIN = 20 * mm
TOP_MARGIN = 18 * mm
BOTTOM_MARGIN = 18 * mm
CONTENT_WIDTH = PAGE[0] - 2 * MARGIN

INK = colors.HexColor("#1B1F24")
MUTED = colors.HexColor("#5B6570")
ACCENT = colors.HexColor("#1A5FB4")
TOC_LEVELS = {"H1": 0, "H2": 1, "H3": 2}

UNICODE_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1]
    head, _, _tail = clipped.rpartition(" ")
    return f"{head or clipped}\u2026"


def _register_unicode_font() -> str | None:
    """Register a broad-coverage font so non-Latin appendices are not blank."""
    for path in UNICODE_FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                pdfmetrics.registerFont(TTFont("UnicodeBody", path))
                return "UnicodeBody"
            except Exception:  # noqa: BLE001 - unusable font file, try the next
                continue
    return None


def build_styles() -> dict[str, ParagraphStyle]:
    body_font, heading_font, code_font = "Times-Roman", "Helvetica-Bold", "Courier"

    def style(name: str, **kwargs) -> ParagraphStyle:
        return ParagraphStyle(name, **kwargs)

    styles = {
        "body": style(
            "Body",
            fontName=body_font,
            fontSize=10.5,
            leading=15.5,
            spaceAfter=7,
            alignment=TA_JUSTIFY,
            textColor=INK,
        ),
        "h1": style(
            "H1",
            fontName=heading_font,
            fontSize=18,
            leading=23,
            spaceBefore=6,
            spaceAfter=10,
            textColor=INK,
        ),
        "h2": style(
            "H2",
            fontName=heading_font,
            fontSize=14,
            leading=19,
            spaceBefore=16,
            spaceAfter=7,
            textColor=INK,
        ),
        "h3": style(
            "H3",
            fontName=heading_font,
            fontSize=11.5,
            leading=16,
            spaceBefore=11,
            spaceAfter=5,
            textColor=colors.HexColor("#30363D"),
        ),
        "h4": style(
            "H4",
            fontName="Helvetica-Oblique",
            fontSize=10.5,
            leading=15,
            spaceBefore=9,
            spaceAfter=4,
            textColor=colors.HexColor("#30363D"),
        ),
        "code": style(
            "Code",
            fontName=code_font,
            fontSize=8.4,
            leading=11.4,
            textColor=colors.HexColor("#24292F"),
        ),
        "quote": style(
            "Quote", fontName=body_font, fontSize=10, leading=14.5, textColor=colors.HexColor("#5C4400")
        ),
        "table_cell": style("TableCell", fontName=body_font, fontSize=9, leading=12.5, textColor=INK),
        "table_header": style(
            "TableHeader", fontName="Helvetica-Bold", fontSize=9, leading=12.5, textColor=INK
        ),
        "title": style(
            "Title",
            fontName=heading_font,
            fontSize=26,
            leading=31,
            alignment=TA_CENTER,
            textColor=INK,
        ),
        "subtitle": style(
            "Subtitle",
            fontName="Helvetica",
            fontSize=13,
            leading=18,
            alignment=TA_CENTER,
            textColor=MUTED,
        ),
        "meta": style(
            "Meta",
            fontName="Helvetica",
            fontSize=9.5,
            leading=14,
            alignment=TA_CENTER,
            textColor=MUTED,
        ),
        "chapter_meta": style(
            "ChapterMeta", fontName="Helvetica", fontSize=9, leading=13, textColor=MUTED
        ),
        "abstract": style(
            "Abstract",
            fontName=body_font,
            fontSize=11,
            leading=16.5,
            alignment=TA_JUSTIFY,
            textColor=INK,
        ),
        "bullet": style(
            "Bullet", fontName=body_font, fontSize=10.5, leading=15, spaceAfter=2, textColor=INK
        ),
        "appendix": style(
            "Appendix", fontName=body_font, fontSize=8.6, leading=12.4, textColor=colors.HexColor("#30363D")
        ),
    }

    # Same look as h1 but a name outside TOC_LEVELS, so it is not indexed itself.
    styles["h1_plain"] = style("H1Plain", parent=styles["h1"])

    if unicode_font := _register_unicode_font():
        styles["appendix_unicode"] = style(
            "AppendixUnicode",
            fontName=unicode_font,
            fontSize=8.6,
            leading=12.8,
            textColor=colors.HexColor("#30363D"),
        )
    return styles


def _toc_styles(styles: dict) -> list[ParagraphStyle]:
    return [
        ParagraphStyle(
            "TOC0",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=18,
            spaceBefore=6,
            textColor=INK,
        ),
        ParagraphStyle(
            "TOC1", fontName="Times-Roman", fontSize=10, leading=15, leftIndent=16, textColor=INK
        ),
        ParagraphStyle(
            "TOC2",
            fontName="Times-Roman",
            fontSize=9,
            leading=13,
            leftIndent=32,
            textColor=MUTED,
        ),
    ]


class NotesDocTemplate(BaseDocTemplate):
    """Adds PDF bookmarks and table-of-contents entries for every heading."""

    def __init__(self, path: Path, *, doc_title: str, footer: str) -> None:
        super().__init__(
            str(path),
            pagesize=PAGE,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=TOP_MARGIN,
            bottomMargin=BOTTOM_MARGIN,
            title=doc_title,
            author="ytexplain",
            subject=footer,
        )
        self.footer = _shorten(footer, 95)
        self._bookmarks = 0
        frame = Frame(
            MARGIN,
            BOTTOM_MARGIN,
            CONTENT_WIDTH,
            PAGE[1] - TOP_MARGIN - BOTTOM_MARGIN,
            id="content",
        )
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=self._decorate)])

    def beforeDocument(self) -> None:
        # multiBuild lays the document out repeatedly; bookmark keys must be
        # identical on every pass or the table of contents never converges.
        self._bookmarks = 0

    def _decorate(self, canvas, _doc) -> None:
        if canvas.getPageNumber() == 1:
            return
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        baseline = BOTTOM_MARGIN - 10
        canvas.drawString(MARGIN, baseline, self.footer)
        canvas.drawRightString(PAGE[0] - MARGIN, baseline, str(canvas.getPageNumber()))
        canvas.setStrokeColor(colors.HexColor("#E1E4E8"))
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, baseline + 9, PAGE[0] - MARGIN, baseline + 9)
        canvas.restoreState()

    def afterFlowable(self, flowable: Flowable) -> None:
        if not isinstance(flowable, Paragraph):
            return
        level = TOC_LEVELS.get(flowable.style.name)
        if level is None:
            return
        text = flowable.getPlainText()
        key = f"h{self._bookmarks}"
        self._bookmarks += 1
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text[:120], key, level=level, closed=level > 0)
        self.notify("TOCEntry", (level, text, self.page, key))


def build_pdf(
    documents: list[Document],
    out_path: Path,
    *,
    include_transcript: bool = False,
    collection_title: str | None = None,
) -> Path:
    if not documents:
        raise ValueError("Nothing to render")

    styles = build_styles()
    renderer = MarkdownRenderer(styles, CONTENT_WIDTH)
    multi = len(documents) > 1
    title = collection_title or documents[0].explainer.title
    footer = f"{title} - generated by ytexplain"

    story: list[Flowable] = _cover(documents, styles, title, multi)
    story += _contents(styles)
    for position, document in enumerate(documents):
        story += _chapter(document, renderer, styles, position, multi, include_transcript)

    with atomic_path(out_path) as temp:
        doc = NotesDocTemplate(temp, doc_title=title, footer=footer)
        doc.multiBuild(story)
    return out_path


def _cover(documents: list[Document], styles: dict, title: str, multi: bool) -> list[Flowable]:
    first = documents[0]
    total_seconds = sum(
        (d.meta.duration or d.transcript.duration or 0) for d in documents
    )
    reading_time = format_reading_time(sum(d.explainer.words for d in documents))
    scope = (
        f"{len(documents)} videos - {format_timestamp(total_seconds)} of video, explained"
        if multi
        else "Written explainer from a YouTube video"
    )
    subtitle = f"{scope} \u00b7 {reading_time} read"
    channels = sorted({d.meta.channel for d in documents if d.meta.channel})
    facts = [
        ("Channel", ", ".join(channels) if channels else None),
        ("Runtime covered", format_timestamp(total_seconds) if total_seconds else None),
        ("Source", first.meta.url if not multi else None),
        (
            "Original language",
            first.explainer.source_language.upper() + " (translated to English)"
            if first.explainer.translated
            else None,
        ),
        ("Model", first.explainer.model),
        ("Generated", datetime.now().astimezone().strftime("%d %b %Y, %H:%M")),
    ]

    story: list[Flowable] = [
        Spacer(1, 55 * mm),
        Paragraph(escape(title), styles["title"]),
        Spacer(1, 6),
        Paragraph(escape(subtitle), styles["subtitle"]),
        Spacer(1, 10),
        HRFlowable(width="35%", thickness=1, color=ACCENT, hAlign="CENTER"),
        Spacer(1, 14),
    ]
    story += [
        Paragraph(f"<b>{escape(label)}:</b> {inline(str(value))}", styles["meta"])
        for label, value in facts
        if value
    ]
    story.append(PageBreak())
    return story


def _contents(styles: dict) -> list[Flowable]:
    toc = TableOfContents()
    toc.levelStyles = _toc_styles(styles)
    toc.dotsMinLevel = 0
    return [
        Paragraph("Contents", styles["h1_plain"]),
        HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#D0D7DE")),
        Spacer(1, 8),
        toc,
        PageBreak(),
    ]


def _chapter(
    document: Document,
    renderer: MarkdownRenderer,
    styles: dict,
    position: int,
    multi: bool,
    include_transcript: bool,
) -> list[Flowable]:
    explainer = document.explainer
    label = f"{position + 1}. {explainer.title}" if multi else explainer.title
    story: list[Flowable] = [
        Paragraph(escape(label), styles["h1"]),
        Paragraph(_chapter_meta(document), styles["chapter_meta"]),
        Spacer(1, 4),
        HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#D0D7DE")),
        Spacer(1, 10),
    ]

    if explainer.abstract:
        story.append(_callout(explainer.abstract, styles, "Overview"))
    if explainer.prerequisites:
        story += _labelled_list("Before you start", explainer.prerequisites, renderer, styles)

    for index, section in enumerate(explainer.sections, start=1):
        heading = Paragraph(f"{index}. {escape(section.heading)}", styles["h2"])
        body = renderer.render(section.body, min_heading=3)
        story.append(KeepTogether([heading, *body[:1]]) if body else heading)
        story += body[1:]

    if explainer.key_terms:
        story += _glossary(explainer.key_terms, styles)
    if explainer.takeaways:
        story += _labelled_list("Key takeaways", explainer.takeaways, renderer, styles)
    if include_transcript:
        story += _appendix(document.transcript, styles)

    story.append(PageBreak())
    return story


def _chapter_meta(document: Document) -> str:
    meta, transcript = document.meta, document.transcript
    parts = [
        part
        for part in (
            meta.channel,
            format_timestamp(meta.duration or transcript.duration),
            f"{format_reading_time(document.explainer.words)} read",
        )
        if part
    ]
    if document.explainer.translated:
        parts.append(f"translated from {document.explainer.source_language}")
    parts.append(f'<link href="{meta.url}" color="#1A5FB4"><u>watch on YouTube</u></link>')
    return " &nbsp;•&nbsp; ".join(parts)


def _callout(text: str, styles: dict, label: str) -> Flowable:
    inner = [
        Paragraph(label.upper(), ParagraphStyle("CalloutLabel", fontName="Helvetica-Bold", fontSize=8, leading=11, textColor=ACCENT)),
        Spacer(1, 4),
        Paragraph(inline(text), styles["abstract"]),
    ]
    table = Table([[inner]], colWidths=[CONTENT_WIDTH])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F6FC")),
                ("LINEBEFORE", (0, 0), (0, -1), 2.5, ACCENT),
                ("LEFTPADDING", (0, 0), (-1, -1), 11),
                ("RIGHTPADDING", (0, 0), (-1, -1), 11),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return table


def _labelled_list(
    label: str, items: list[str], renderer: MarkdownRenderer, styles: dict
) -> list[Flowable]:
    markdown = "\n".join(f"- {item}" for item in items)
    return [Paragraph(escape(label), styles["h2"]), *renderer.render(markdown)]


def _glossary(terms: list[tuple[str, str]], styles: dict) -> list[Flowable]:
    rows = [
        [Paragraph(f"<b>{escape(term)}</b>", styles["table_cell"]), Paragraph(inline(definition), styles["table_cell"])]
        for term, definition in terms
    ]
    table = Table(rows, colWidths=[CONTENT_WIDTH * 0.28, CONTENT_WIDTH * 0.72])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#E1E4E8")),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return [Paragraph("Glossary", styles["h2"]), table, Spacer(1, 8)]


def _appendix(transcript: Transcript, styles: dict) -> list[Flowable]:
    style = styles.get("appendix_unicode" if transcript.script != "latin" else "appendix", styles["appendix"])
    story: list[Flowable] = [
        Paragraph("Appendix: source transcript", styles["h2"]),
        Paragraph(
            f"Captions as retrieved ({transcript.language_code}, "
            f"{'auto-generated' if transcript.is_generated else 'human-written'}, via {transcript.source}).",
            styles["chapter_meta"],
        ),
        Spacer(1, 8),
    ]
    story += [
        Paragraph(f"<b>{format_timestamp(start)}</b> &nbsp;{escape(text)}", style)
        for start, text in transcript.blocks(window=45.0)
    ]
    return story
