"""Writes an LLM-decided table (columns + rows) out as an .xlsx workbook, via openpyxl.

`ExportDocumentInput`'s validator guarantees `columns`/`rows` are both present
whenever `format="excel"` — there is no fallback path here for freeform
`content`, a spreadsheet has to be tabular.
"""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from taskflowassistant.dedicated_tools.table_utils import row_value

_MAX_SHEET_TITLE_LENGTH = 31  # Excel's own hard limit on sheet names.


def write_excel_file(title: str, columns: list[str], rows: list[dict], path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:_MAX_SHEET_TITLE_LENGTH] or "Sheet1"

    sheet.append(columns)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for row in rows:
        sheet.append([row_value(row, column) for column in columns])

    for idx in range(1, len(columns) + 1):
        sheet.column_dimensions[get_column_letter(idx)].width = 24

    workbook.save(path)
    return path
