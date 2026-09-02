"""FastMCP server exposing TaskFlow operations as MCP tools.

Every tool here only validates input (via the schemas in `mcp/models.py`) and
delegates to `TaskFlowClient` — no request-building/HTTP logic lives in this
file, that all lives in `connection/taskflow_client.py`.

Tools are grouped into three domains, matching the TaskFlow DOTNET Backend's
Postman collection:
- Task domain    — Tasks + Board Statuses
- Teams domain   — Teams + Roles/Permissions
- Workspace domain — People (workspace membership) + Workspace + Users

A few tools resolve "the caller" (a user or workspace id) from the bearer
token itself via `connection/jwt_utils.py` rather than accepting it as a
model-supplied argument — either because the parameter is optional and
defaults to "me" for convenience (Users domain), or because accepting it from
the caller would reproduce a real IDOR in the backend (`get_my_permissions`).

Run standalone with the `taskflow-mcp-server` console script, or let the
agent spawn it automatically over stdio via `mcp/client.py`.
"""

from mcp.server.fastmcp import FastMCP

from taskflowassistant.connection.config import config
from taskflowassistant.connection.jwt_utils import current_user_id, current_workspace_id
from taskflowassistant.connection.taskflow_client import TaskFlowClient
from taskflowassistant.mcp.models import (
    ChangeTaskStatusInput,
    CreateBoardStatusInput,
    CreateTaskInput,
    CreateTeamInput,
    DeleteBoardStatusInput,
    DeleteTaskInput,
    DeleteTeamInput,
    EnlistWorkspaceMembersInput,
    GetBoardInput,
    GetMyPermissionsInput,
    GetMyTasksInput,
    GetPendingInvitationsInput,
    GetTaskInput,
    GetTeamInput,
    GetUserByIdInput,
    GetUserSettingsInput,
    GetWorkspaceInfoInput,
    InviteToTeamInput,
    ListBoardStatusesInput,
    ListTasksInput,
    ListTeamsInput,
    ListUsersInput,
    ListWorkspacePeopleInput,
    RemoveTeamMemberInput,
    RemoveWorkspaceMemberInput,
    RespondToInvitationInput,
    SendWorkspaceInvitationInput,
    UpdateTaskInput,
    UpdateTeamInput,
    UpdateUserPasswordInput,
    UpdateUserProfileInput,
    UpdateUserSettingsInput,
    UpdateWorkspaceMemberInput,
)
from taskflowassistant.mcp.utils.response_trimming import (
    trim_board,
    trim_board_status,
    trim_person,
    trim_result,
    trim_task,
    trim_team,
    trim_user,
)

mcp = FastMCP("taskflow-mcp-server")


def _resolve_user_id(explicit: object) -> str:
    """Return `explicit` if given, else the caller's own user id from their token."""
    if explicit is not None:
        return str(explicit)
    resolved = current_user_id(config["TASKFLOW_API_TOKEN"])
    if not resolved:
        raise ValueError(
            "No user id was given and the caller's own id couldn't be read from the "
            "TaskFlow token — pass an explicit user id."
        )
    return resolved


def _resolve_workspace_id(explicit: object) -> str:
    """Return `explicit` if given, else the caller's own workspace id from their token."""
    if explicit is not None:
        return str(explicit)
    resolved = current_workspace_id(config["TASKFLOW_API_TOKEN"])
    if not resolved:
        raise ValueError(
            "No workspace id was given and the caller's own workspace id couldn't be read "
            "from the TaskFlow token — pass an explicit workspace id."
        )
    return resolved


# =====================================================================
# Task domain (Tasks + Board Statuses)
# =====================================================================


@mcp.tool()
async def create_task(payload: CreateTaskInput) -> object:
    """Create a new task in TaskFlow."""
    async with TaskFlowClient() as client:
        return await client.create_task(payload.model_dump(by_alias=True, exclude_none=True, mode="json"))


@mcp.tool()
async def get_task(payload: GetTaskInput) -> object:
    """Fetch a single TaskFlow task by its id."""
    async with TaskFlowClient() as client:
        return await client.get_task(payload.task_id)


@mcp.tool()
async def list_tasks(payload: ListTasksInput) -> object:
    """List TaskFlow tasks, optionally filtered by search text, team, status, or assignee.

    For "what's assigned to me" questions, prefer `get_my_tasks` instead — it's
    a single already-filtered call rather than listing everyone's tasks and
    filtering client-side.
    """
    async with TaskFlowClient() as client:
        params = payload.model_dump(by_alias=True, exclude_none=True, mode="json")
        result = await client.list_tasks(params)
    return trim_result(result, trim_task)


@mcp.tool()
async def get_my_tasks(payload: GetMyTasksInput) -> object:
    """List tasks assigned to the current user, optionally filtered by search text or team.

    A single backend call already scoped to the caller — prefer this over
    `list_tasks` plus manual filtering whenever the question is about "my"
    tasks.
    """
    async with TaskFlowClient() as client:
        params = payload.model_dump(by_alias=True, exclude_none=True, mode="json")
        result = await client.get_my_tasks(params)
    return trim_result(result, trim_task)


@mcp.tool()
async def get_board(payload: GetBoardInput) -> object:
    """Fetch a team's full Kanban board: every status column with its tasks, in one call.

    Prefer this single call over calling `list_board_statuses` and then
    `list_tasks` per status and stitching the board together yourself.
    """
    async with TaskFlowClient() as client:
        result = await client.get_board(payload.team_id)
    return trim_board(result)


@mcp.tool()
async def update_task(payload: UpdateTaskInput) -> object:
    """Update one or more fields of an existing TaskFlow task (including its status)."""
    async with TaskFlowClient() as client:
        return await client.update_task(payload.task_id, payload.to_update_dict())


@mcp.tool()
async def delete_task(payload: DeleteTaskInput) -> object:
    """Delete a TaskFlow task by its id. This is a hard delete — its comments cascade-delete with it."""
    async with TaskFlowClient() as client:
        return await client.delete_task(payload.task_id)


@mcp.tool()
async def change_task_status(payload: ChangeTaskStatusInput) -> object:
    """Move a task to a different board column/status (e.g. a drag-and-drop status change)."""
    async with TaskFlowClient() as client:
        return await client.change_task_status(payload.task_id, payload.to_body_dict())


@mcp.tool()
async def list_board_statuses(payload: ListBoardStatusesInput) -> object:
    """List a team's board statuses (columns, e.g. 'Backlog', 'In Progress', 'Done')."""
    async with TaskFlowClient() as client:
        result = await client.list_board_statuses(payload.team_id)
    return trim_result(result, trim_board_status)


@mcp.tool()
async def create_board_status(payload: CreateBoardStatusInput) -> object:
    """Add a custom board column (status) to a team's Kanban board."""
    async with TaskFlowClient() as client:
        return await client.create_board_status(payload.model_dump(by_alias=True, exclude_none=True, mode="json"))


@mcp.tool()
async def delete_board_status(payload: DeleteBoardStatusInput) -> object:
    """Delete a custom board column. Fails on the 3 seeded default columns (not deletable);
    on success, all tasks (and their comments) in that column are cascade-deleted."""
    async with TaskFlowClient() as client:
        return await client.delete_board_status(payload.status_id)


# =====================================================================
# Teams domain (Teams + Roles/Permissions)
# =====================================================================


@mcp.tool()
async def list_teams(payload: ListTeamsInput) -> object:
    """List the teams the current user belongs to. Use this to resolve a team name to its id."""
    async with TaskFlowClient() as client:
        result = await client.list_teams(payload.exclude_workspace)
    return trim_result(result, trim_team)


@mcp.tool()
async def get_team(payload: GetTeamInput) -> object:
    """Fetch a single team's full details: name, description, members, metadata."""
    async with TaskFlowClient() as client:
        return await client.get_team(payload.team_id)


@mcp.tool()
async def get_team_stats() -> object:
    """Get aggregate statistics across the caller's teams (e.g. task counts, member counts, activity)."""
    async with TaskFlowClient() as client:
        return await client.get_team_stats()


@mcp.tool()
async def create_team(payload: CreateTeamInput) -> object:
    """Create a new team in the workspace. The caller is auto-assigned the Admin role on it."""
    async with TaskFlowClient() as client:
        return await client.create_team(payload.model_dump(by_alias=True, exclude_none=True, mode="json"))


@mcp.tool()
async def update_team(payload: UpdateTeamInput) -> object:
    """Update a team's name/description/color, and/or replace its full member list.
    Requires the caller's role on the team to include the `Manage` permission."""
    async with TaskFlowClient() as client:
        return await client.update_team(payload.team_id, payload.to_update_dict())


@mcp.tool()
async def delete_team(payload: DeleteTeamInput) -> object:
    """Permanently delete a team and all its associated data."""
    async with TaskFlowClient() as client:
        return await client.delete_team(payload.team_id)


@mcp.tool()
async def invite_to_team(payload: InviteToTeamInput) -> object:
    """Invite someone to a specific team by email. Requires the caller's role on the
    team to include the `Manage` permission."""
    async with TaskFlowClient() as client:
        return await client.invite_to_team(payload.team_id, payload.to_body_dict())


@mcp.tool()
async def remove_team_member(payload: RemoveTeamMemberInput) -> object:
    """Remove a member from a team (they remain a workspace member — use
    remove_workspace_member to remove them from the whole workspace instead)."""
    async with TaskFlowClient() as client:
        return await client.remove_team_member(payload.team_id, payload.target_user_id)


@mcp.tool()
async def get_roles() -> object:
    """List the predefined roles (Admin, PM, TL, Developer) and their permissions.
    Use this to resolve a role name to the roleId needed by team invite/update/create tools."""
    async with TaskFlowClient() as client:
        return await client.get_roles()


@mcp.tool()
async def get_my_permissions(payload: GetMyPermissionsInput) -> object:
    """Get the caller's own role and permissions on a team.

    Always scoped to the caller — there's no way to pass another user's id
    through this tool, because the underlying backend endpoint doesn't check
    that a caller-supplied userId belongs to them.
    """
    user_id = _resolve_user_id(None)
    async with TaskFlowClient() as client:
        return await client.get_permissions(payload.team_id, user_id)


# =====================================================================
# Workspace domain (People + Workspace + Users)
# =====================================================================


@mcp.tool()
async def list_workspace_people(payload: ListWorkspacePeopleInput) -> object:
    """Search workspace members, to resolve a person's name/email to their user id."""
    async with TaskFlowClient() as client:
        params = payload.model_dump(by_alias=True, exclude_none=True, mode="json")
        result = await client.list_workspace_people(params)
    return trim_result(result, trim_person)


@mcp.tool()
async def get_workspace_stats() -> object:
    """Get aggregate workspace statistics: total members, active users, team counts."""
    async with TaskFlowClient() as client:
        return await client.get_workspace_stats()


@mcp.tool()
async def send_workspace_invitation(payload: SendWorkspaceInvitationInput) -> object:
    """Invite someone to the TaskFlow workspace by email."""
    async with TaskFlowClient() as client:
        return await client.send_workspace_invitation(payload.email)


@mcp.tool()
async def update_workspace_member(payload: UpdateWorkspaceMemberInput) -> object:
    """Update a workspace member's details (e.g. their title)."""
    async with TaskFlowClient() as client:
        return await client.update_workspace_member(payload.user_id, payload.to_update_dict())


@mcp.tool()
async def remove_workspace_member(payload: RemoveWorkspaceMemberInput) -> object:
    """Remove a member from the whole workspace (removes them from all teams too)."""
    async with TaskFlowClient() as client:
        return await client.remove_workspace_member(payload.user_id)


@mcp.tool()
async def enlist_workspace_members(payload: EnlistWorkspaceMembersInput) -> object:
    """Bulk-add existing users as workspace members in a single call."""
    async with TaskFlowClient() as client:
        return await client.enlist_workspace_members([str(uid) for uid in payload.user_ids])


@mcp.tool()
async def accept_workspace_invitation(payload: RespondToInvitationInput) -> object:
    """Accept a pending workspace invitation on behalf of a given user."""
    async with TaskFlowClient() as client:
        return await client.accept_workspace_invitation(payload.model_dump(by_alias=True, mode="json"))


@mcp.tool()
async def decline_workspace_invitation(payload: RespondToInvitationInput) -> object:
    """Decline a pending workspace invitation on behalf of a given user."""
    async with TaskFlowClient() as client:
        return await client.decline_workspace_invitation(payload.model_dump(by_alias=True, mode="json"))


@mcp.tool()
async def get_pending_invitations(payload: GetPendingInvitationsInput) -> object:
    """List a user's pending workspace invitations. Defaults to the caller if no user id is given."""
    user_id = _resolve_user_id(payload.user_id)
    async with TaskFlowClient() as client:
        return await client.get_pending_invitations(user_id)


@mcp.tool()
async def get_workspace_info(payload: GetWorkspaceInfoInput) -> object:
    """Get workspace details: owner, teams, and members. Defaults to the caller's own workspace."""
    workspace_id = _resolve_workspace_id(payload.workspace_id)
    async with TaskFlowClient() as client:
        return await client.get_workspace_info(workspace_id)


@mcp.tool()
async def list_users(payload: ListUsersInput) -> object:
    """List users, optionally filtered by name/email search or workspace."""
    async with TaskFlowClient() as client:
        params = payload.model_dump(by_alias=True, exclude_none=True, mode="json")
        result = await client.list_users(params)
    return trim_result(result, trim_user)


@mcp.tool()
async def get_user_by_id(payload: GetUserByIdInput) -> object:
    """Fetch a specific user's profile by id."""
    async with TaskFlowClient() as client:
        return await client.get_user_by_id(payload.user_id)


@mcp.tool()
async def update_user_profile(payload: UpdateUserProfileInput) -> object:
    """Update a user's profile (name, title, avatar). Defaults to the caller if no user id is given."""
    user_id = _resolve_user_id(payload.user_id)
    async with TaskFlowClient() as client:
        return await client.update_user_profile(user_id, payload.to_update_dict())


@mcp.tool()
async def get_user_settings(payload: GetUserSettingsInput) -> object:
    """Get a user's app settings (notifications, theme, language, archive policy).
    Defaults to the caller if no user id is given."""
    user_id = _resolve_user_id(payload.user_id)
    async with TaskFlowClient() as client:
        return await client.get_user_settings(user_id)


@mcp.tool()
async def update_user_settings(payload: UpdateUserSettingsInput) -> object:
    """Update a user's app settings. Defaults to the caller if no user id is given."""
    user_id = _resolve_user_id(payload.user_id)
    async with TaskFlowClient() as client:
        return await client.update_user_settings(user_id, payload.to_update_dict())


@mcp.tool()
async def update_user_password(payload: UpdateUserPasswordInput) -> object:
    """Change a user's password. Defaults to the caller if no user id is given."""
    user_id = _resolve_user_id(payload.user_id)
    async with TaskFlowClient() as client:
        return await client.update_user_password(user_id, payload.to_body_dict())


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
