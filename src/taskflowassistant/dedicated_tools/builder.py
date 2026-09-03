"""Picks the right per-format exporter and decides where the file lands on disk.

Purely a rendering dispatcher — the caller (`mcp/server.py`'s `export_document`
tool) has already decided the actual content; nothing here fetches data or
imposes a fixed schema.
"""

import re
import uuid
from pathlib import Path
from typing import Literal

from taskflowassistant.dedicated_tools.excel_export import write_excel_file
from taskflowassistant.dedicated_tools.markdown_export import write_markdown_file
from taskflowassistant.dedicated_tools.pdf_export import write_pdf_file
from taskflowassistant.dedicated_tools.store import EXPORTS_DIR

ExportFormat = Literal["markdown", "excel", "pdf"]

_EXTENSIONS: dict[ExportFormat, str] = {"markdown": "md", "excel": "xlsx", "pdf": "pdf"}


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()
    return slug or "export"


def build_export_file(
    export_format: ExportFormat,
    title: str,
    content: str | None,
    columns: list[str] | None,
    rows: list[dict] | None,
) -> tuple[str, Path]:
    """Render `content` (or `columns`/`rows`) as `export_format` and return
    (display_filename, path_on_disk).

    `display_filename` (derived from `title`) is what the user sees as the
    downloaded file's name; the on-disk path uses a random name so two
    exports with the same title never collide.
    """
    extension = _EXTENSIONS[export_format]
    display_filename = f"{_slugify(title)}.{extension}"

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORTS_DIR / f"{uuid.uuid4().hex}.{extension}"

    if export_format == "markdown":
        write_markdown_file(title, content, columns, rows, path)
    elif export_format == "excel":
        # ExportDocumentInput's validator guarantees columns/rows are both
        # present whenever format="excel".
        write_excel_file(title, columns, rows, path)
    else:
        write_pdf_file(title, content, columns, rows, path)

    return display_filename, path
