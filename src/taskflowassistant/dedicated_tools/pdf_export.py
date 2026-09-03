"""Writes LLM-composed content (freeform Markdown, or a table) out as a PDF, via reportlab.

Pure-Python (no native/system dependencies) so it works identically on
Windows dev machines and the Linux Docker deploy — deliberately not
WeasyPrint (HTML/CSS -> PDF, nicer styling but needs Pango/Cairo/GDK-Pixbuf,
which are painful on Windows and would make local testing Docker-only).

`content` is plain-Markdown-ish text the model writes (headings, bullets,
`**bold**`/`*italic*`) — this is a small, deliberately limited renderer for
that subset, not a general Markdown parser.

A PDF is a document, not a spreadsheet — even when the caller passes
`columns`/`rows` (table mode), each row is rendered as its own heading + a
bulleted list of its fields (via the same Markdown renderer `content` uses),
not as a grid `Table`. An earlier version used a real `Table` here; with
more than a handful of columns or any long cell text, reportlab lays it out
at its natural (unconstrained) width and the page simply clips whatever
doesn't fit — columns get cut off the left/right edges instead of wrapping.
Table layout stays exactly right for `excel_export.py`, where a literal grid
is the actual point.
"""

import re
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")


def _inline_markup(text: str) -> str:
    """Map the common inline Markdown to the mini-HTML reportlab's Paragraph understands."""
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_RE.sub(r"<i>\1</i>", text)
    return text


def _markdown_to_flowables(content: str, styles) -> list:
    flowables: list = []
    bullet_buffer: list[str] = []

    def flush_bullets() -> None:
        if not bullet_buffer:
            return
        items = [ListItem(Paragraph(_inline_markup(text), styles["Normal"])) for text in bullet_buffer]
        flowables.append(ListFlowable(items, bulletType="bullet"))
        bullet_buffer.clear()

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            flush_bullets()
            flowables.append(Spacer(1, 6))
        elif line.startswith("### "):
            flush_bullets()
            flowables.append(Paragraph(_inline_markup(line[4:]), styles["Heading3"]))
        elif line.startswith("## "):
            flush_bullets()
            flowables.append(Paragraph(_inline_markup(line[3:]), styles["Heading2"]))
        elif line.startswith("# "):
            flush_bullets()
            flowables.append(Paragraph(_inline_markup(line[2:]), styles["Heading1"]))
        elif line.startswith(("- ", "* ")):
            bullet_buffer.append(line[2:])
        else:
            flush_bullets()
            flowables.append(Paragraph(_inline_markup(line), styles["Normal"]))

    flush_bullets()
    return flowables


def _rows_to_document_markdown(columns: list[str], rows: list[dict]) -> str:
    """Turn a table into per-row Markdown sections: the first column's value
    becomes each row's heading, every other column becomes a bold-labeled
    bullet — the same "one card per item" shape `write_markdown_file` and
    the pre-generalization task exporter used, just derived from whatever
    columns the caller actually gave instead of a fixed task schema.
    """
    if not columns:
        return ""

    heading_column, *detail_columns = columns
    lines: list[str] = []

    for row in rows:
        heading_value = row.get(heading_column)
        lines.append(f"## {heading_value if heading_value not in (None, '') else 'Untitled'}")
        for column in detail_columns:
            value = row.get(column)
            if value in (None, ""):
                continue
            lines.append(f"- **{column}:** {value}")
        lines.append("")

    return "\n".join(lines)


def write_pdf_file(
    title: str,
    content: str | None,
    columns: list[str] | None,
    rows: list[dict] | None,
    path: Path,
) -> Path:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=LETTER)
    story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]

    if columns and rows is not None:
        story.extend(_markdown_to_flowables(_rows_to_document_markdown(columns, rows), styles))
    elif content:
        story.extend(_markdown_to_flowables(content, styles))
    else:
        story.append(Paragraph("No content provided for this export.", styles["Normal"]))

    doc.build(story)
    return path
