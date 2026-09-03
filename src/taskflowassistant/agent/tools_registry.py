"""Assembles every tool the TaskFlow agent is allowed to use.

`executor.py` only ever awaits `get_tools()` from here — it doesn't know or
care where each tool came from.

This is async because loading MCP tools is inherently async
(`MultiServerMCPClient.get_tools()` is a coroutine) — it can't be collapsed
into a plain module-level list without blocking the event loop at import
time, which would also break under a FastAPI app (no `asyncio.run()` inside
an already-running loop).
"""

from langchain_core.tools import BaseTool

from taskflowassistant.dedicated_tools.export_tool import export_document
from taskflowassistant.mcp.client import load_mcp_tools
from taskflowassistant.rag.retriever import get_retriever_tool

async def get_tools(taskflow_token: str | None = None) -> list[BaseTool]:
    """Return every tool the agent should have access to.

    `taskflow_token`, if given, is forwarded to the MCP server so its
    TaskFlow tools act on behalf of the actual caller for this request.
    """

    # Gettings mcp tools
    mcp_tools = await load_mcp_tools(taskflow_token)

    # Getting rag tools
    rag_tools = [get_retriever_tool()]

    # Dedicated tools — NOT loaded via MCP on purpose: these need to run in
    # this same process (see dedicated_tools/export_tool.py's docstring for
    # why), not the separate subprocess the MCP tools above are spawned into.
    dedicated_tools = [export_document]

    return mcp_tools + rag_tools + dedicated_tools
