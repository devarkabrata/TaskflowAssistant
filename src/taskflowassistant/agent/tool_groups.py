"""Domain groupings for the TaskFlow MCP tools.

Splitting the ~38 MCP tools into domain-scoped subsets lets each specialist
agent (agent/flow_nodes/specialist_agent.py) bind only its own ~6-12 tool
schemas to the model instead of all of them at once — see
agent/flow_nodes/supervisor.py's docstring for why that matters. This module
only groups tool NAMES; the actual BaseTool objects come from
mcp/client.py's load_mcp_tools() and are matched up in tools_registry.py.
"""

from langchain_core.tools import BaseTool

TASK_TOOL_NAMES = {
    "create_task",
    "get_task",
    "list_tasks",
    "get_my_tasks",
    "get_board",
    "update_task",
    "delete_task",
    "change_task_status",
    "list_board_statuses",
    "create_board_status",
    "delete_board_status",
}

TEAM_TOOL_NAMES = {
    "list_teams",
    "get_team",
    "get_team_stats",
    "create_team",
    "update_team",
    "delete_team",
    "invite_to_team",
    "remove_team_member",
    "get_roles",
    "get_my_permissions",
}

WORKSPACE_TOOL_NAMES = {
    "list_workspace_people",
    "get_workspace_stats",
    "send_workspace_invitation",
    "update_workspace_member",
    "remove_workspace_member",
    "enlist_workspace_members",
    "accept_workspace_invitation",
    "decline_workspace_invitation",
    "get_pending_invitations",
    "get_workspace_info",
}

USER_ADMIN_TOOL_NAMES = {
    "list_users",
    "get_user_by_id",
    "update_user_profile",
    "get_user_settings",
    "update_user_settings",
    "update_user_password",
}

# `get_current_user` is deliberately bound nowhere below: flow_nodes/
# hydrate_user.py already fetches it once per thread with no LLM call at
# all, and every specialist's prompt is told the result is already in its
# own context (agent/flow_nodes/_identity.py) — binding it anywhere would
# just be schema weight with no upside.

# `knowledge` has no MCP tools of its own (see tools_registry.py, which adds
# the RAG retriever tool for it) — it's also the catch-all for greetings and
# general TaskFlow questions that don't fit any of the CRUD-shaped domains
# below, which is why it isn't listed here.
MCP_TOOL_GROUPS: dict[str, set[str]] = {
    "task": TASK_TOOL_NAMES,
    "team": TEAM_TOOL_NAMES,
    "workspace": WORKSPACE_TOOL_NAMES,
    "user_admin": USER_ADMIN_TOOL_NAMES,
}

# Single source of truth for every valid specialist name — used by
# flow_nodes/supervisor.py (routing decision), graph_executor.py (building
# one node + edge per name), and tools_registry.py (grouped tool dict keys).
SPECIALIST_NAMES: tuple[str, ...] = (*MCP_TOOL_GROUPS.keys(), "knowledge")


def partition_mcp_tools(mcp_tools: list[BaseTool]) -> dict[str, list[BaseTool]]:
    """Split the flat MCP tool list into the domain groups above.

    An MCP tool not named in any group above (currently just
    `get_current_user`) is silently left out of every specialist's bound
    subset — it stays perfectly callable if anything else ever needs it
    (e.g. the shared ToolNode's execution-side list), it's just never
    offered to a specialist's model call.
    """
    by_name = {tool.name: tool for tool in mcp_tools}
    return {
        group: [by_name[name] for name in names if name in by_name]
        for group, names in MCP_TOOL_GROUPS.items()
    }
