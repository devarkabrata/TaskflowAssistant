"""Document-export tools: renders TaskFlow tasks as Markdown/Excel/PDF files.

Kept as its own top-level package (a sibling of `mcp/`, `agent/`, `connection/`,
`rag/`) rather than nested inside any of those — it's a distinct concern
(file generation + a download-serving registry), not agent orchestration or
API-client logic.
"""
