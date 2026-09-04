"""Fetches the caller's own TaskFlow profile once per thread and caches it in state.

`get_current_user` (GET /auth/me) is the reliable way to learn who the
caller is — their user id, workspace, and team memberships. Decoding the
bearer token's JWT claims for this used to be tried first as a
no-network-call shortcut (see the now-deleted `connection/jwt_utils.py`), but
real tokens often don't carry a usable workspace claim at all, making that
path unreliable; `mcp/server.py`'s own self-resolution helpers
(`_resolve_user_id`/`_resolve_workspace_id`) were simplified for the same
reason.

Rather than spend one of the agent's own tool calls on `get_current_user`
every time it needs this (or every turn of a long conversation), this node
fetches it directly via `TaskFlowClient` — no LLM involved, no tool-calling
round trip — the first time a thread runs, and caches the result in
`state["current_user"]`. That's a plain checkpointed field (see
`schema/state.py`), so it survives for the rest of the conversation: every
later turn's call to this node is a cheap no-op. `flow_nodes/specialist_agent.py`
(and `flow_nodes/supervisor.py`) then inject the cached profile into their
prompts so the model already knows it on every turn, and is told not to call
the `get_current_user` tool again unless the user explicitly asks for a
refresh.
"""

from taskflowassistant.agent.schema.state import TaskFlowState
from taskflowassistant.connection.taskflow_client import TaskFlowClient


async def hydrate_user_node(state: TaskFlowState) -> dict:
    if state.get("current_user"):
        return {}

    async with TaskFlowClient(token=state.get("taskflow_token")) as client:
        profile = await client.get_current_user()

    return {"current_user": profile}
