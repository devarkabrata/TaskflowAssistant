"""The `export_document` tool — a plain LangChain tool, deliberately NOT an MCP tool.

Every other tool the agent has lives in `mcp/server.py` and is loaded via
`mcp/client.py`'s `load_mcp_tools`, which spawns the MCP server as its own
separate OS subprocess (`MCP_TRANSPORT=stdio` by default — see
`connection/config.py`). That's fine for those tools: they're stateless
wrappers around TaskFlow backend HTTP calls, so which process runs them
doesn't matter.

This tool is different: `dedicated_tools/store.py`'s file registry is a
plain in-process dict, and `main.py`'s `GET /files/{file_id}` route (which
serves the generated file) needs to read the SAME dict that `register_file`
wrote to. If this tool lived in `mcp/server.py`, it would run in the
spawned subprocess and populate a registry that only exists in that child
process's memory — invisible to `main.py`, so every download would 404
despite the tool call itself succeeding. Defining it here and appending it
in `agent/tools_registry.py` keeps it in the SAME process as `main.py`,
so the registry is actually shared.
"""

from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field, model_validator

from taskflowassistant.dedicated_tools.builder import build_export_file
from taskflowassistant.dedicated_tools.store import register_file

ExportFormat = Literal["markdown", "excel", "pdf"]


class ExportDocumentInput(BaseModel):
    """Turn content you've already gathered and composed into a downloadable file.

    This does NOT fetch or decide what goes in the document — gather the
    underlying data first with other tools (list_tasks, get_my_tasks,
    get_board, list_teams, etc.), decide what belongs in the document
    yourself (which items, how to group them, what to call out), and only
    then call this tool with:
    - `content` — freeform Markdown text you write (headings, bullets, bold)
      for a narrative document, e.g. a meeting agenda or summary; or
    - `columns` + `rows` — a table you decide both the headers and data for.
      Required for format="excel"; also works for format="pdf" instead of
      `content` — for pdf, each row becomes its own heading (from the first
      column) with the rest of its fields as bullets underneath, laid out as
      a document rather than a spreadsheet grid, so it never overflows the
      page even with many columns or long values.
    """

    format: ExportFormat = Field(..., description="Output document format: 'markdown', 'excel', or 'pdf'.")
    title: str = Field(..., min_length=1, description="Document heading/title, and the base of its filename.")
    content: str | None = Field(None, description="Freeform Markdown-formatted text you've composed.")
    columns: list[str] | None = Field(None, description="Table column headers, in the order they should appear.")
    rows: list[dict[str, str | int | float | bool | None]] | None = Field(
        None, description="Table rows — each dict's keys should match `columns`."
    )

    @model_validator(mode="after")
    def _check_content_shape(self) -> "ExportDocumentInput":
        has_table = bool(self.columns) and self.rows is not None
        has_content = bool(self.content)
        if self.format == "excel" and not has_table:
            raise ValueError(
                "format='excel' requires both `columns` and `rows` (a table) — "
                "`content` alone can't become a spreadsheet."
            )
        if not has_table and not has_content:
            raise ValueError("Provide either `content` (freeform Markdown text) or `columns` + `rows` (a table).")
        return self


@tool(args_schema=ExportDocumentInput)
def export_document(
    format: ExportFormat,
    title: str,
    content: str | None = None,
    columns: list[str] | None = None,
    rows: list[dict] | None = None,
) -> dict:
    """Turn content you've already gathered and composed into a downloadable file
    (Markdown, Excel, or PDF) — e.g. "give me a 2-day meeting agenda as a PDF" or
    "export that as an Excel sheet".

    This tool does NOT fetch or decide what goes in the document. Gather the
    underlying data first with other tools (list_tasks, get_my_tasks, get_board,
    list_teams, etc.), decide what belongs in the document yourself (which items,
    how to group them, what to call out), and only then call this tool with:
    - `content` — freeform Markdown text you write (headings, bullets, bold) for a
      narrative document, e.g. a meeting agenda or summary; or
    - `columns` + `rows` — a table you decide both the headers and data for.
      Required for format="excel"; also works for format="pdf" instead of `content`
      (rendered there as a document — one heading + bullet list per row — not a
      spreadsheet grid).

    Returns a small JSON result (filename, format, download URL) — NEVER the
    file's actual bytes. Tell the user their file is ready and give them the link;
    don't try to read, quote, or repeat the file's contents, you were never sent them.
    """
    filename, path = build_export_file(format, title, content, columns, rows)
    file_id = register_file(path, filename)

    return {
        "filename": filename,
        "format": format,
        "downloadUrl": f"/files/{file_id}",
    }
