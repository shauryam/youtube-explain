"""Render the Markdown subset the model emits into ReportLab flowables.

Supported: ATX headings, paragraphs, nested bullet/ordered lists, fenced code
blocks, blockquotes, pipe tables, horizontal rules, and inline bold, italic,
strikethrough, code spans and links.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from reportlab.lib import colors
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    XPreformatted,
)

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*([A-Za-z0-9+#._-]*)\s*$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
ORDERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
QUOTE = re.compile(r"^\s*>\s?(.*)$")
RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_DIVIDER = re.compile(r"^\s*\|(?:\s*:?-{2,}:?\s*\|)+\s*$")

CODE_SPAN = re.compile(r"`([^`]+)`")
BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
STRIKE = re.compile(r"~~(.+?)~~", re.DOTALL)
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)[^)]*\)")
PLACEHOLDER = "\x00{}\x00"
PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline(text: str, code_font: str = "Courier", code_color: str = "#B5285B") -> str:
    """Convert inline Markdown into ReportLab's paragraph markup."""
    spans: list[str] = []

    def stash(match: re.Match[str]) -> str:
        spans.append(escape(match.group(1)))
        return PLACEHOLDER.format(len(spans) - 1)

    text = CODE_SPAN.sub(stash, text)
    text = escape(text)
    text = LINK.sub(r'<link href="\2" color="#1A5FB4"><u>\1</u></link>', text)
    text = BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = ITALIC.sub(r"<i>\1</i>", text)
    text = STRIKE.sub(r"<strike>\1</strike>", text)
    return PLACEHOLDER_RE.sub(
        lambda m: f'<font face="{code_font}" color="{code_color}">{spans[int(m.group(1))]}</font>',
        text,
    )


@dataclass(slots=True)
class _ListNode:
    ordered: bool
    items: list[tuple[str, list[_ListNode]]] = field(default_factory=list)


class MarkdownRenderer:
    """Stateless across calls: one instance can render many documents."""

    def __init__(self, styles: dict, content_width: float) -> None:
        self.styles = styles
        self.content_width = content_width
        self.code_font = styles["code"].fontName
        self._min_heading = 1

    def render(self, markdown: str, min_heading: int = 1) -> list[Flowable]:
        """`min_heading` floors heading levels so nested content cannot outrank
        the heading the caller placed above it."""
        self._min_heading = min_heading
        lines = markdown.replace("\r\n", "\n").replace("\t", "    ").split("\n")
        flows: list[Flowable] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
                continue
            for handler in (
                self._fence,
                self._table,
                self._heading,
                self._rule,
                self._quote,
                self._list,
            ):
                consumed = handler(lines, index, flows)
                if consumed:
                    index += consumed
                    break
            else:
                index += self._paragraph(lines, index, flows)
        return flows

    def _p(self, text: str, style_key: str = "body") -> Paragraph:
        return Paragraph(inline(text, self.code_font), self.styles[style_key])

    def _heading(self, lines: list[str], index: int, flows: list[Flowable]) -> int:
        match = HEADING.match(lines[index])
        if not match:
            return 0
        level = max(self._min_heading, min(len(match.group(1)), 4))
        flows.append(self._p(match.group(2).strip(), f"h{level}"))
        return 1

    def _rule(self, lines: list[str], index: int, flows: list[Flowable]) -> int:
        if not RULE.match(lines[index]):
            return 0
        flows.append(Spacer(1, 4))
        flows.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#D0D7DE")))
        flows.append(Spacer(1, 6))
        return 1

    def _fence(self, lines: list[str], index: int, flows: list[Flowable]) -> int:
        opening = FENCE.match(lines[index])
        if not opening:
            return 0
        marker = opening.group(1)[0]
        body: list[str] = []
        cursor = index + 1
        while cursor < len(lines):
            closing = FENCE.match(lines[cursor])
            if closing and closing.group(1)[0] == marker:
                cursor += 1
                break
            body.append(lines[cursor])
            cursor += 1

        code = XPreformatted(escape("\n".join(body).rstrip()), self.styles["code"])
        frame = Table([[code]], colWidths=[self.content_width])
        frame.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F6F8FA")),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D0D7DE")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        flows.extend([Spacer(1, 4), frame, Spacer(1, 8)])
        return cursor - index

    def _quote(self, lines: list[str], index: int, flows: list[Flowable]) -> int:
        if not QUOTE.match(lines[index]):
            return 0
        collected: list[str] = []
        cursor = index
        while cursor < len(lines) and (match := QUOTE.match(lines[cursor])):
            collected.append(match.group(1).strip())
            cursor += 1

        text = " ".join(part for part in collected if part)
        quote = Table([[self._p(text, "quote")]], colWidths=[self.content_width])
        quote.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF8E1")),
                    ("LINEBEFORE", (0, 0), (0, -1), 2.5, colors.HexColor("#E5A50A")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        flows.extend([Spacer(1, 4), quote, Spacer(1, 8)])
        return cursor - index

    def _list(self, lines: list[str], index: int, flows: list[Flowable]) -> int:
        if not (BULLET.match(lines[index]) or ORDERED.match(lines[index])):
            return 0
        entries: list[tuple[int, bool, str]] = []
        cursor = index
        while cursor < len(lines):
            line = lines[cursor]
            if bullet := BULLET.match(line):
                entries.append((len(bullet.group(1)), False, bullet.group(2).strip()))
            elif ordered := ORDERED.match(line):
                entries.append((len(ordered.group(1)), True, ordered.group(3).strip()))
            elif line.strip() and entries and line.startswith((" ", "\t")):
                depth, ordered_flag, text = entries[-1]
                entries[-1] = (depth, ordered_flag, f"{text} {line.strip()}")
            else:
                break
            cursor += 1

        node = self._build_list(entries, 0, 0)[0]
        flows.extend([self._list_flowable(node), Spacer(1, 6)])
        return cursor - index

    def _build_list(
        self, entries: list[tuple[int, bool, str]], position: int, depth: int
    ) -> tuple[_ListNode, int]:
        node = _ListNode(ordered=entries[position][1])
        while position < len(entries):
            indent, _ordered, text = entries[position]
            if indent < depth:
                break
            if indent > depth and node.items:
                child, position = self._build_list(entries, position, indent)
                node.items[-1][1].append(child)
                continue
            node.items.append((text, []))
            position += 1
        return node, position

    def _list_flowable(self, node: _ListNode, depth: int = 0) -> ListFlowable:
        items: list[ListItem] = []
        for text, children in node.items:
            content: list[Flowable] = [self._p(text, "bullet")]
            for child in children:
                content.append(self._list_flowable(child, depth + 1))
            items.append(ListItem(content, leftIndent=12, spaceBefore=1, spaceAfter=1))
        common = {
            "bulletFontName": self.styles["body"].fontName,
            "bulletFontSize": self.styles["body"].fontSize,
            "leftIndent": 14 + depth * 8,
            "bulletDedent": 10,
        }
        if node.ordered:
            return ListFlowable(items, bulletType="1", bulletFormat="%s.", start=1, **common)
        return ListFlowable(items, bulletType="bullet", start="\u2022" if depth == 0 else "\u2013", **common)

    def _table(self, lines: list[str], index: int, flows: list[Flowable]) -> int:
        if not TABLE_ROW.match(lines[index]):
            return 0
        rows: list[list[str]] = []
        cursor = index
        has_header = False
        while cursor < len(lines) and TABLE_ROW.match(lines[cursor]):
            if TABLE_DIVIDER.match(lines[cursor]):
                has_header = bool(rows)
                cursor += 1
                continue
            rows.append([cell.strip() for cell in lines[cursor].strip().strip("|").split("|")])
            cursor += 1

        if not rows:
            return cursor - index or 1

        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        data = [
            [
                self._p(cell, "table_header" if has_header and r == 0 else "table_cell")
                for cell in row
            ]
            for r, row in enumerate(rows)
        ]

        table = Table(data, colWidths=self._column_widths(rows), repeatRows=1 if has_header else 0)
        style = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D7DE")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        if has_header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2F6")))
        table.setStyle(TableStyle(style))
        flows.extend([Spacer(1, 4), table, Spacer(1, 10)])
        return cursor - index

    def _column_widths(self, rows: list[list[str]]) -> list[float]:
        columns = len(rows[0])
        weights = [
            max(len(row[column]) for row in rows) or 1 for column in range(columns)
        ]
        floor = 0.4 / columns
        shares = [max(weight / sum(weights), floor) for weight in weights]
        total = sum(shares)
        return [self.content_width * share / total for share in shares]

    def _paragraph(self, lines: list[str], index: int, flows: list[Flowable]) -> int:
        collected: list[str] = []
        cursor = index
        while cursor < len(lines):
            line = lines[cursor]
            if not line.strip() or self._starts_block(line):
                break
            collected.append(line.strip())
            cursor += 1
        if collected:
            flows.append(self._p(" ".join(collected)))
        return max(cursor - index, 1)

    @staticmethod
    def _starts_block(line: str) -> bool:
        return bool(
            HEADING.match(line)
            or FENCE.match(line)
            or BULLET.match(line)
            or ORDERED.match(line)
            or QUOTE.match(line)
            or RULE.match(line)
            or TABLE_ROW.match(line)
        )