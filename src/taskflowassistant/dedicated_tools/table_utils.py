"""Shared, tolerant column-name lookup for the table exporters.

Observed in production: the model doesn't always key `rows` with the exact
same strings it put in `columns` — e.g. `columns=["Task Title", "Due Date"]`
alongside `rows=[{"TaskTitle": ..., "DueDate": ...}]`. A literal `row[column]`
/ `row.get(column)` then silently returns nothing for every row (rendered as
a blank cell, or "Untitled" for a PDF heading) instead of erroring — the
worst kind of failure, since the output looks complete at a glance. This
normalizes both sides (case, whitespace, punctuation) before matching so
"Task Title" and "TaskTitle" resolve to the same field.
"""

import re

_STRIP_RE = re.compile(r"[^a-z0-9]")


def _normalize(key: str) -> str:
    return _STRIP_RE.sub("", key.lower())


def row_value(row: dict, column: str):
    """Look up `column`'s value in `row`, tolerant of case/space/punctuation
    differences between the declared column header and the row's actual key.
    Returns None if no key in `row` matches `column` even loosely.
    """
    if column in row:
        return row[column]
    target = _normalize(column)
    for key, value in row.items():
        if _normalize(key) == target:
            return value
    return None
