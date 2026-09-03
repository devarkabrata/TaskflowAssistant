"""Writes LLM-composed content (freeform Markdown, or a table) out as a .md file.

Deliberately dumb: it never fetches or decides what the document contains —
see `mcp/models.py`'s `ExportDocumentInput` — it just lays out whichever of
`content`/`columns`+`rows` was given.
"""

from pathlib import Path

from taskflowassistant.dedicated_tools.table_utils import row_value


def _render_table(columns: list[str], rows: list[dict]) -> str:
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body_lines = [
        "| "
        + " | ".join(
            "" if row_value(row, col) is None else str(row_value(row, col)) for col in columns
        )
        + " |"
        for row in rows
    ]
    return "\n".join([header, separator, *body_lines])


def build_markdown(
    title: str,
    content: str | None,
    columns: list[str] | None,
    rows: list[dict] | None,
) -> str:
    lines = [f"# {title}", ""]

    if columns and rows is not None:
        lines.append(_render_table(columns, rows))
    elif content:
        lines.append(content)
    else:
        lines.append("_No content provided for this export._")

    return "\n".join(lines)


def write_markdown_file(
    title: str,
    content: str | None,
    columns: list[str] | None,
    rows: list[dict] | None,
    path: Path,
) -> Path:
    path.write_text(build_markdown(title, content, columns, rows), encoding="utf-8")
    return path
