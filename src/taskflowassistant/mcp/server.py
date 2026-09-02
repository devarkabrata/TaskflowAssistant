"""FastMCP server exposing TaskFlow operations as MCP tools.

Every tool here only validates input (via the schemas in `mcp/models.py`) and
delegates to `TaskFlowClient` — no request-building/HTTP logic lives in this
file, that all lives in `connection/taskflow_client.py`.

Tools are grouped into four domains, matching the TaskFlow DOTNET Backend's
Postman collection:
- Identity       — `get_current_user` (GET /auth/me): the caller's own full
  profile, including which workspace/teams they belong to. This is the
  starting point for ANY "who am I" / "what teams am I in" / "my email"
  style question — see its docstring below before reaching for
  get_workspace_info, list_teams, or list_workspace_people for that instead.
- Task domain    — Tasks + Board Statuses
- Teams domain   — Teams + Roles/Permissions
- Workspace domain — People (workspace membership) + Workspace + Users

Docstrings on each tool are written for the calling LLM, not just humans —
each one says not just what the tool does, but when to prefer it over a
similarly-shaped tool, and what id it needs resolved first (and via which
tool) if it takes one. Read a tool's own docstring at call time; don't infer
behavior from its name alone (e.g. the two "Remove Member" style tools below
differ in blast radius, not just name).

A few tools resolve "the caller" (a user or workspace id) rather than
accepting one as a model-supplied argument — either because the parameter is
optional and defaults to "me" for convenience (Users domain), or because
accepting it from the caller would reproduce a real IDOR in the backend
(`get_my_permissions`). That resolution first tries the bearer token's own
claims (`connection/jwt_utils.py`, no network call) and, if the token doesn't
carry them, falls back to a live `get_current_user` call — see
`_resolve_user_id`/`_resolve_workspace_id`.

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
    pick_first,
    trim_board,
    trim_board_status,
    trim_person,
    trim_result,
    trim_task,
    trim_team,
    trim_user,
)

mcp = FastMCP("taskflow-mcp-server")


async def _current_user_profile() -> dict:
    """Fetch the caller's own `/auth/me` profile, for use as a resolution fallback."""
    async with TaskFlowClient() as client:
        return await client.get_current_user()


async def _resolve_user_id(explicit: object) -> str:
    """Return `explicit` if given, else the caller's own user id.

    Tries the bearer token's own claims first (no network call); if the
    token doesn't carry a usable id, falls back to a live `get_current_user`
    call.
    """
    if explicit is not None:
        return str(explicit)
    token_user_id = current_user_id(config["TASKFLOW_API_TOKEN"])
    if token_user_id:
        return token_user_id
    profile = await _current_user_profile()
    resolved = pick_first(profile, "id", "Id", "userId", "UserId")
    if not resolved:
        raise ValueError(
            "No user id was given, and the caller's own id couldn't be read from the "
            "TaskFlow token or resolved via get_current_user — pass an explicit user id."
        )
    return str(resolved)


async def _resolve_workspace_id(explicit: object) -> str:
    """Return `explicit` if given, else the caller's own workspace id.

    Tries the bearer token's own claims first (no network call); if the
    token doesn't carry a usable id, falls back to a live `get_current_user`
    call (checking both a top-level `workspaceId` and a nested `workspace.id`).
    """
    if explicit is not None:
        return str(explicit)
    token_workspace_id = current_workspace_id(config["TASKFLOW_API_TOKEN"])
    if token_workspace_id:
        return token_workspace_id
    profile = await _current_user_profile()
    resolved = pick_first(profile, "workspaceId", "WorkspaceId")
    if not resolved:
        workspace = pick_first(profile, "workspace", "Workspace")
        if isinstance(workspace, dict):
            resolved = pick_first(workspace, "id", "Id")
    if not resolved:
        raise ValueError(
            "No workspace id was given, and the caller's own workspace id couldn't be read "
            "from the TaskFlow token or resolved via get_current_user — pass an explicit "
            "workspace id."
        )
    return str(resolved)


# =====================================================================
# Identity
# =====================================================================


@mcp.tool()
async def get_current_user() -> object:
    """Get the caller's OWN full profile: id, name, email, avatar, role, and which
    workspace/teams they belong to.

    Call this FIRST — before get_workspace_info, list_teams, or
    list_workspace_people — for any question about the caller themself:
    "who am I", "what's my email", "what teams am I on", "what workspace am
    I in", "what's my role". It takes no arguments and answers directly from
    the caller's own account record, so it's a single call instead of
    combining several lookup tools and hoping the caller shows up in the
    results. Only reach for get_user_by_id/list_workspace_people/list_teams
    when the question is about someone/something ELSE, not the caller.
    """
    async with TaskFlowClient() as client:
        return await client.get_current_user()


# =====================================================================
# Task domain (Tasks + Board Statuses)
# =====================================================================


@mcp.tool()
async def create_task(payload: CreateTaskInput) -> object:
    """Create a new task on a team's board.

    Needs real ids, not names — never guess a GUID. Resolve `team_id` via
    `list_teams`, `status_id` via `list_board_statuses` (or `get_board`), and
    any `assignee_ids` via `list_workspace_people`, before calling this.
    """
    async with TaskFlowClient() as client:
        return await client.create_task(payload.model_dump(by_alias=True, exclude_none=True, mode="json"))


@mcp.tool()
async def get_task(payload: GetTaskInput) -> object:
    """Fetch one task's full details by its exact task id.

    Only use this once you already have the id (e.g. from `list_tasks`,
    `get_my_tasks`, or `get_board`). To find a task by title, team, or
    status instead of by id, use one of those tools first.
    """
    async with TaskFlowClient() as client:
        return await client.get_task(payload.task_id)


@mcp.tool()
async def list_tasks(payload: ListTasksInput) -> object:
    """Search/list tasks across teams, with optional filters (search text, team,
    status, assignee) and pagination — the general-purpose task search tool.

    Prefer a more specific tool when the question fits it better:
    - "my tasks" / "what do I have to do" -> `get_my_tasks` (already scoped
      to the caller, no need to pass your own assignee id here).
    - "show me team X's board" / "what's in To Do for team X" -> `get_board`
      (every column with its tasks in one call — cheaper than filtering
      `list_tasks` by status yourself).
    Use `list_tasks` itself for cross-team searches, free-text search, or
    filtering by someone else's assignee id.
    """
    async with TaskFlowClient() as client:
        params = payload.model_dump(by_alias=True, exclude_none=True, mode="json")
        result = await client.list_tasks(params)
    return trim_result(result, trim_task)


@mcp.tool()
async def get_my_tasks(payload: GetMyTasksInput) -> object:
    """List tasks assigned to the CALLER, optionally filtered by search text or team.

    This is the direct tool for "my tasks" / "what's assigned to me" /
    "what do I need to do" questions — one already-server-filtered call,
    instead of calling `list_tasks` and filtering the results yourself.
    """
    async with TaskFlowClient() as client:
        params = payload.model_dump(by_alias=True, exclude_none=True, mode="json")
        result = await client.get_my_tasks(params)
    return trim_result(result, trim_task)


@mcp.tool()
async def get_board(payload: GetBoardInput) -> object:
    """Fetch a team's ENTIRE Kanban board — every status column together with its
    tasks — in a single call.

    This is the right tool whenever the question is about a team's board or
    tasks-grouped-by-status as a whole (e.g. "what's in To Do for team X",
    "how many tasks are In Progress", "show me the board"). Requires
    `team_id` — resolve it via `list_teams` first if you only have a team
    name. Prefer this single call over `list_board_statuses` followed by
    `list_tasks` per status and grouping them yourself — that's strictly
    more tool calls for data this already returns pre-grouped.
    """
    async with TaskFlowClient() as client:
        result = await client.get_board(payload.team_id)
    return trim_board(result)


@mcp.tool()
async def update_task(payload: UpdateTaskInput) -> object:
    """Update one or more fields of an existing task (title, description, priority,
    label, status, assignees, due date, progress) — every field but `task_id`
    is optional; send only what's actually changing.

    If you are ONLY moving a task to a different column/status, prefer
    `change_task_status` instead — same effect, smaller payload. Use
    `update_task` for everything else, or when changing status alongside
    other fields in the same call.
    """
    async with TaskFlowClient() as client:
        return await client.update_task(payload.task_id, payload.to_update_dict())


@mcp.tool()
async def delete_task(payload: DeleteTaskInput) -> object:
    """Permanently delete a task by id.

    Hard delete, not reversible — its comments cascade-delete with it. If
    there's any ambiguity about which task is meant, confirm the id first
    (e.g. via `get_task` or `list_tasks`) rather than guessing.
    """
    async with TaskFlowClient() as client:
        return await client.delete_task(payload.task_id)


@mcp.tool()
async def change_task_status(payload: ChangeTaskStatusInput) -> object:
    """Move a single task to a different board column/status — the direct,
    minimal-payload way to do a status change (the drag-and-drop equivalent).

    Requires `status_id` — resolve it via `list_board_statuses` or
    `get_board` first, never guess a column name into a GUID. To change
    status alongside other fields in the same call, use `update_task`
    instead (it also accepts a `status_id`).
    """
    async with TaskFlowClient() as client:
        return await client.change_task_status(payload.task_id, payload.to_body_dict())


@mcp.tool()
async def list_board_statuses(payload: ListBoardStatusesInput) -> object:
    """List a team's board columns/statuses — id, name, position (e.g. 'To Do',
    'In Progress', 'Done').

    Use this to resolve a column NAME to the `status_id` that `create_task`,
    `update_task`, `change_task_status`, and `create_board_status` require.
    If you also need each column's tasks (not just the column list itself),
    `get_board` is the single-call alternative that returns both together.
    """
    async with TaskFlowClient() as client:
        result = await client.list_board_statuses(payload.team_id)
    return trim_result(result, trim_board_status)


@mcp.tool()
async def create_board_status(payload: CreateBoardStatusInput) -> object:
    """Add a NEW custom column to a team's Kanban board (e.g. add a 'Code Review'
    column).

    This defines a new status/column itself — it does NOT create or move any
    task. To put a task into an existing column, use `create_task` or
    `change_task_status` with that column's `status_id` instead.
    """
    async with TaskFlowClient() as client:
        return await client.create_board_status(payload.model_dump(by_alias=True, exclude_none=True, mode="json"))


@mcp.tool()
async def delete_board_status(payload: DeleteBoardStatusInput) -> object:
    """Delete a custom board column.

    Fails on the 3 seeded default columns (To Do / In Progress / Done — not
    deletable). Destructive: cascade-deletes every task (and its comments)
    still in that column. If you need to confirm what's in it first, check
    `list_board_statuses` or `get_board`.
    """
    async with TaskFlowClient() as client:
        return await client.delete_board_status(payload.status_id)


# =====================================================================
# Teams domain (Teams + Roles/Permissions)
# =====================================================================


@mcp.tool()
async def list_teams(payload: ListTeamsInput) -> object:
    """List every team the caller belongs to — id, name, description.

    THE tool to resolve a team name mentioned by the user into the
    `team_id` that almost every Task/Board/Team tool requires (in TaskFlow,
    what a user calls a "project" is usually a Team). For "what teams am I
    on" as a standalone identity question, `get_current_user` may already
    answer it in one call — reach for `list_teams` when you specifically
    need to search/resolve a team by name, or want the full list.
    """
    async with TaskFlowClient() as client:
        result = await client.list_teams(payload.exclude_workspace)
    return trim_result(result, trim_team)


@mcp.tool()
async def get_team(payload: GetTeamInput) -> object:
    """Fetch one team's full details (name, description, members, metadata) by its
    exact `team_id`.

    Use `list_teams` first if you only have the team's name, not its id.
    """
    async with TaskFlowClient() as client:
        return await client.get_team(payload.team_id)


@mcp.tool()
async def get_team_stats() -> object:
    """Get aggregate statistics across ALL of the caller's teams at once (task
    counts, member counts, activity).

    Takes no arguments and is NOT scoped to a single team — there is no
    per-team stats endpoint; for one team's own detail use `get_team` or
    `get_board` instead.
    """
    async with TaskFlowClient() as client:
        return await client.get_team_stats()


@mcp.tool()
async def create_team(payload: CreateTeamInput) -> object:
    """Create a brand-new team in the workspace.

    The caller is auto-assigned the Admin role on it automatically —
    `member_ids` is only for additional members to add up front, each
    paired with a `role_id` from `get_roles` (resolve a role NAME to its id
    there first, never guess a GUID).
    """
    async with TaskFlowClient() as client:
        return await client.create_team(payload.model_dump(by_alias=True, exclude_none=True, mode="json"))


@mcp.tool()
async def update_team(payload: UpdateTeamInput) -> object:
    """Rename/redescribe/recolor a team, and/or replace its ENTIRE member list, in
    one call.

    Requires the caller's role on the team to include the `Manage`
    permission — check with `get_my_permissions` first if unsure. If you set
    `members`, it's a full REPLACEMENT, not a merge: include everyone who
    should remain (the team admin included), or they're removed.
    """
    async with TaskFlowClient() as client:
        return await client.update_team(payload.team_id, payload.to_update_dict())


@mcp.tool()
async def delete_team(payload: DeleteTeamInput) -> object:
    """Permanently delete a team and everything under it (tasks, board columns,
    comments).

    Not reversible. If there's any doubt which team is meant, confirm the
    `team_id` first (e.g. via `list_teams` or `get_team`) rather than
    guessing.
    """
    async with TaskFlowClient() as client:
        return await client.delete_team(payload.team_id)


@mcp.tool()
async def invite_to_team(payload: InviteToTeamInput) -> object:
    """Invite someone to a SPECIFIC team by email.

    Not for inviting to the whole workspace — use `send_workspace_invitation`
    for that. Requires the caller's role on the team to include `Manage`,
    and a `role_id` from `get_roles` for what the invitee will hold once
    they accept.
    """
    async with TaskFlowClient() as client:
        return await client.invite_to_team(payload.team_id, payload.to_body_dict())


@mcp.tool()
async def remove_team_member(payload: RemoveTeamMemberInput) -> object:
    """Remove someone from ONE team only.

    They remain a workspace member and stay on any other teams they're on.
    To remove them from the WHOLE workspace (every team at once), use
    `remove_workspace_member` instead.
    """
    async with TaskFlowClient() as client:
        return await client.remove_team_member(payload.team_id, payload.target_user_id)


@mcp.tool()
async def get_roles() -> object:
    """List the predefined roles (Admin, PM, TL, Developer) and the permissions
    each carries (Read/Write/Delete/Manage/Comment).

    Call this whenever a role NAME needs to become the `role_id` that
    `create_team`, `update_team`, and `invite_to_team` require — never guess
    a role's GUID.
    """
    async with TaskFlowClient() as client:
        return await client.get_roles()


@mcp.tool()
async def get_my_permissions(payload: GetMyPermissionsInput) -> object:
    """Get the CALLER'S OWN role and permissions on one team — e.g. to check
    whether they'll be allowed to `update_team`, `invite_to_team`, or
    `delete_board_status` before attempting it.

    Always scoped to the caller: there is no way to check someone else's
    permissions through this tool (the underlying endpoint has no ownership
    check on a caller-supplied user id, so this tool deliberately never
    exposes one).
    """
    user_id = await _resolve_user_id(None)
    async with TaskFlowClient() as client:
        return await client.get_permissions(payload.team_id, user_id)


# =====================================================================
# Workspace domain (People + Workspace + Users)
# =====================================================================


@mcp.tool()
async def list_workspace_people(payload: ListWorkspacePeopleInput) -> object:
    """Search/list workspace members — id, name, email, status — optionally
    filtered to one team's members via `team_id`.

    Use this to resolve a person mentioned by name/email into the user id
    that `assignee_ids`/`target_user_id`/`user_id` parameters need
    elsewhere. For the CALLER's own identity, use `get_current_user`
    instead of searching for themself here.
    """
    async with TaskFlowClient() as client:
        params = payload.model_dump(by_alias=True, exclude_none=True, mode="json")
        result = await client.list_workspace_people(params)
    return trim_result(result, trim_person)


@mcp.tool()
async def get_workspace_stats() -> object:
    """Get aggregate workspace-wide statistics: total members, active users, team
    counts. Takes no arguments."""
    async with TaskFlowClient() as client:
        return await client.get_workspace_stats()


@mcp.tool()
async def send_workspace_invitation(payload: SendWorkspaceInvitationInput) -> object:
    """Invite someone to the WHOLE workspace by email.

    Not scoped to any one team — use `invite_to_team` for that instead. A
    workspace invitee joins with no team assigned yet; add them to a team
    afterward via `invite_to_team` or `update_team`.
    """
    async with TaskFlowClient() as client:
        return await client.send_workspace_invitation(payload.email)


@mcp.tool()
async def update_workspace_member(payload: UpdateWorkspaceMemberInput) -> object:
    """Update a workspace member's details (currently: their title).

    For updating the CALLER's own profile (name/title/avatar),
    `update_user_profile` is the more complete tool. A member's ROLE is set
    per-team via `update_team`'s member list, not here.
    """
    async with TaskFlowClient() as client:
        return await client.update_workspace_member(payload.user_id, payload.to_update_dict())


@mcp.tool()
async def remove_workspace_member(payload: RemoveWorkspaceMemberInput) -> object:
    """Remove someone from the ENTIRE workspace — every team they're on, not just
    one.

    For removing them from a SINGLE team only, use `remove_team_member`
    instead.
    """
    async with TaskFlowClient() as client:
        return await client.remove_workspace_member(payload.user_id)


@mcp.tool()
async def enlist_workspace_members(payload: EnlistWorkspaceMembersInput) -> object:
    """Bulk-add existing users (already registered, just not workspace members
    yet) as workspace members in one call.

    Not for inviting new people who don't have an account yet by email —
    that's `send_workspace_invitation`.
    """
    async with TaskFlowClient() as client:
        return await client.enlist_workspace_members([str(uid) for uid in payload.user_ids])


@mcp.tool()
async def accept_workspace_invitation(payload: RespondToInvitationInput) -> object:
    """Accept a pending workspace invitation for a given user + workspace.

    Both ids must be given explicitly — this backend endpoint is anonymous
    (a brand-new invitee may not have a session token yet), so there is no
    caller identity to default them from.
    """
    async with TaskFlowClient() as client:
        return await client.accept_workspace_invitation(payload.model_dump(by_alias=True, mode="json"))


@mcp.tool()
async def decline_workspace_invitation(payload: RespondToInvitationInput) -> object:
    """Decline a pending workspace invitation for a given user + workspace.

    Both ids must be given explicitly — this backend endpoint is anonymous
    (a brand-new invitee may not have a session token yet), so there is no
    caller identity to default them from.
    """
    async with TaskFlowClient() as client:
        return await client.decline_workspace_invitation(payload.model_dump(by_alias=True, mode="json"))


@mcp.tool()
async def get_pending_invitations(payload: GetPendingInvitationsInput) -> object:
    """List a user's pending (not yet accepted/declined) workspace invitations.

    Omit `user_id` to check the CALLER's own pending invitations; pass an
    explicit one only to check someone else's.
    """
    user_id = await _resolve_user_id(payload.user_id)
    async with TaskFlowClient() as client:
        return await client.get_pending_invitations(user_id)


@mcp.tool()
async def get_workspace_info(payload: GetWorkspaceInfoInput) -> object:
    """Get workspace-level details — owner, teams, and members — together in one
    call.

    Omit `workspace_id` to get the CALLER's own workspace. For "what teams
    am I in" as a pure identity question, `get_current_user` is more direct;
    use `get_workspace_info` when the question is about the workspace as a
    structure (who owns it, its full team/member roster) rather than the
    caller specifically.
    """
    workspace_id = await _resolve_workspace_id(payload.workspace_id)
    async with TaskFlowClient() as client:
        return await client.get_workspace_info(workspace_id)


@mcp.tool()
async def list_users(payload: ListUsersInput) -> object:
    """Search/list users by name or email, optionally scoped to a workspace — a
    system-wide user directory.

    This is distinct from `list_workspace_people`, which is scoped to
    workspace-membership records (status, team filtering). Prefer
    `list_workspace_people` for "who's on my team/workspace" questions; use
    `list_users` for a broader user lookup not tied to workspace membership.
    """
    async with TaskFlowClient() as client:
        params = payload.model_dump(by_alias=True, exclude_none=True, mode="json")
        result = await client.list_users(params)
    return trim_result(result, trim_user)


@mcp.tool()
async def get_user_by_id(payload: GetUserByIdInput) -> object:
    """Fetch a specific user's profile by id.

    For the CALLER's OWN profile, use `get_current_user` instead — it's
    already scoped to them and needs no id.
    """
    async with TaskFlowClient() as client:
        return await client.get_user_by_id(payload.user_id)


@mcp.tool()
async def update_user_profile(payload: UpdateUserProfileInput) -> object:
    """Update a user's profile (name, title, avatar).

    Omit `user_id` to update the CALLER's own profile (the common case);
    pass an explicit id only to update someone else's.
    """
    user_id = await _resolve_user_id(payload.user_id)
    async with TaskFlowClient() as client:
        return await client.update_user_profile(user_id, payload.to_update_dict())


@mcp.tool()
async def get_user_settings(payload: GetUserSettingsInput) -> object:
    """Get a user's app settings (notifications, theme, language, archive policy).

    Omit `user_id` to get the CALLER's own settings; pass an explicit id
    only to check someone else's.
    """
    user_id = await _resolve_user_id(payload.user_id)
    async with TaskFlowClient() as client:
        return await client.get_user_settings(user_id)


@mcp.tool()
async def update_user_settings(payload: UpdateUserSettingsInput) -> object:
    """Update a user's app settings.

    Omit `user_id` to update the CALLER's own settings (the common case);
    pass an explicit id only to update someone else's.
    """
    user_id = await _resolve_user_id(payload.user_id)
    async with TaskFlowClient() as client:
        return await client.update_user_settings(user_id, payload.to_update_dict())


@mcp.tool()
async def update_user_password(payload: UpdateUserPasswordInput) -> object:
    """Change a user's password.

    Omit `user_id` to change the CALLER's own password (the common case);
    pass an explicit id only to change someone else's.
    """
    user_id = await _resolve_user_id(payload.user_id)
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
