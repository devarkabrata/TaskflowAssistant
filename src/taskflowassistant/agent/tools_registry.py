"""Assembles the TaskFlow agent's tools, grouped by domain for the
supervisor/specialist multi-agent design (see agent/flow_nodes/supervisor.py).

Each specialist owns its own tools AND its own `ToolNode` (built from the
same list in graph_executor.py) — there is no shared tool-execution node
across domains.
"""

from langchain_core.tools import BaseTool

from taskflowassistant.agent.handoff_tools import make_handoff_tools
from taskflowassistant.agent.tool_groups import SPECIALIST_NAMES, partition_mcp_tools
from taskflowassistant.dedicated_tools.export_tool import export_document
from taskflowassistant.mcp.client import load_mcp_tools
from taskflowassistant.rag.retriever import get_retriever_tool


async def get_grouped_tools(taskflow_token: str | None = None) -> dict[str, list[BaseTool]]:
    """Return the tools bound to (and executed by) each specialist, by domain.

    `taskflow_token`, if given, is forwarded to the MCP server so its
    TaskFlow tools act on behalf of the actual caller for this request.
    One MCP subprocess spawn total — every group is derived from the same
    `load_mcp_tools()` call, not a separate one per domain.

    `export_document` is added to every group — any specialist should be
    able to turn its own domain's data into a downloadable file without a
    separate hop. `knowledge` gets the RAG retriever tool and doubles as the
    catch-all for greetings/general TaskFlow questions that don't fit any of
    the CRUD-shaped domains. Every group also gets its own handoff tools
    (agent/handoff_tools.py) — one `handoff_to_X` per OTHER domain — so a
    specialist can explicitly pass a request to a different domain via a
    real tool call instead of the supervisor re-guessing afterward.
    """
    mcp_tools = await load_mcp_tools(taskflow_token)
    grouped = partition_mcp_tools(mcp_tools)
    grouped["knowledge"] = [get_retriever_tool()]

    for domain, group_tools in grouped.items():
        group_tools.append(export_document)
        group_tools.extend(make_handoff_tools(domain, SPECIALIST_NAMES))

    return grouped
