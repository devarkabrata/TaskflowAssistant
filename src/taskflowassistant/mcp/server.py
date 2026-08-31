"""FastMCP server exposing TaskFlow operations as MCP tools.

Every tool here only validates input (via the schemas in `mcp/tools.py`) and
delegates to `TaskFlowClient` — no request-building/HTTP logic lives in this
file, that all lives in `connection/taskflow_client.py`.

Run standalone with the `taskflow-mcp-server` console script, or let the
agent spawn it automatically over stdio via `mcp/client.py`.
"""

from mcp.server.fastmcp import FastMCP

from taskflowassistant.connection.config import config
from taskflowassistant.connection.taskflow_client import TaskFlowClient
from taskflowassistant.mcp.models import (
    CreateTaskInput,
    DeleteTaskInput,
    GetTaskInput,
    ListBoardStatusesInput,
    ListTasksInput,
    ListTeamsInput,
    ListWorkspacePeopleInput,
    SendWorkspaceInvitationInput,
    UpdateTaskInput,
)
from taskflowassistant.mcp.utils.response_trimming import trim_team, trim_board_status, trim_person, trim_result, trim_task

mcp = FastMCP("taskflow-mcp-server")


@mcp.tool()
async def create_task(payload: CreateTaskInput) -> object:
    """Create a new task in TaskFlow."""
    async with TaskFlowClient() as client:
        return await client.create_task(payload.model_dump(exclude_none=True, mode="json"))


@mcp.tool()
async def get_task(payload: GetTaskInput) -> object:
    """Fetch a single TaskFlow task by its id."""
    async with TaskFlowClient() as client:
        return await client.get_task(payload.task_id)


@mcp.tool()
async def list_tasks(payload: ListTasksInput) -> object:
    """List TaskFlow tasks, optionally filtered by search text, team, status, or assignee."""
    async with TaskFlowClient() as client:
        result = await client.list_tasks(payload.model_dump(exclude_none=True, mode="json"))
    return trim_result(result, trim_task)


@mcp.tool()
async def update_task(payload: UpdateTaskInput) -> object:
    """Update one or more fields of an existing TaskFlow task (including its status)."""
    async with TaskFlowClient() as client:
        return await client.update_task(payload.task_id, payload.to_update_dict())


@mcp.tool()
async def delete_task(payload: DeleteTaskInput) -> object:
    """Delete a TaskFlow task by its id."""
    async with TaskFlowClient() as client:
        return await client.delete_task(payload.task_id)


@mcp.tool()
async def list_teams(payload: ListTeamsInput) -> object:
    """List the teams the current user belongs to. Use this to resolve a team name to its id."""
    async with TaskFlowClient() as client:
        result = await client.list_teams(payload.exclude_workspace)
    return trim_result(result, trim_team)


@mcp.tool()
async def list_board_statuses(payload: ListBoardStatusesInput) -> object:
    """List a team's board statuses (columns, e.g. 'Backlog', 'In Progress', 'Done')."""
    async with TaskFlowClient() as client:
        result = await client.list_board_statuses(payload.team_id)
    return trim_result(result, trim_board_status)


@mcp.tool()
async def list_workspace_people(payload: ListWorkspacePeopleInput) -> object:
    """Search workspace members, to resolve a person's name/email to their user id."""
    async with TaskFlowClient() as client:
        result = await client.list_workspace_people(payload.search, payload.page, payload.limit)
    return trim_result(result, trim_person)


@mcp.tool()
async def send_workspace_invitation(payload: SendWorkspaceInvitationInput) -> object:
    """Invite someone to the TaskFlow workspace by email."""
    async with TaskFlowClient() as client:
        return await client.send_workspace_invitation(payload.email)


def main() -> None:
    """Entry point for the `taskflow-mcp-server` console script.

    Transport is picked from `.env` (`MCP_TRANSPORT`) so the same server
    code can run either as a subprocess spawned over stdio, or as a
    standalone long-running HTTP server other clients connect to.
    """
    if config["MCP_TRANSPORT"] == "streamable_http":
        mcp.settings.host = config["MCP_SERVER_HOST"]
        mcp.settings.port = config["MCP_SERVER_PORT"]
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
