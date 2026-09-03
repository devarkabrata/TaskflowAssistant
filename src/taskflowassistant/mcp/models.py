"""Pydantic input schemas for each TaskFlow MCP tool.

Field names mirror the real .NET DTOs in TaskFlowBackend/DTOs (Tasks, Teams,
Workspaces, People, Users, Roles, BoardStatuses — see the matching
Controllers), so what the agent sends is always valid without any translation
layer.

Every model inherits `CamelModel`, which auto-generates a camelCase alias for
each snake_case field (`team_id` -> `teamId`) to match the backend's
System.Text.Json wire format. Tools must call
`payload.model_dump(by_alias=True, exclude_none=True, mode="json")` (or use
the `to_*_dict()` helpers below) — plain `model_dump()` without `by_alias`
would send snake_case keys the backend doesn't bind to.

Two fields intentionally keep a *misspelled* alias (`isArchievable`,
`daysToArchieve`) because that's the real, already-shipped wire name in the
backend DTOs (confirmed against the Postman collection) — fixing the spelling
here would just silently break the request.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel

Priority = Literal["High", "Medium", "Low"]
Label = Literal["Feature", "Bug", "Design", "Docs", "Infra", "Refactor"]


class CamelModel(BaseModel):
    """Base for every tool input: snake_case in Python, camelCase on the wire."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# --- Tasks (TaskController, /tasks) ---


class CreateTaskInput(CamelModel):
    """Arguments for creating a new TaskFlow task. Matches CreateTaskRequestDto."""

    title: str = Field(..., min_length=1, max_length=500, description="Task title.")
    description: str | None = Field(None, description="Optional longer description.")
    priority: Priority = Field(..., description="Task priority.")
    label: Label | None = Field(None, description="Optional single label/category.")
    status_id: uuid.UUID = Field(
        ..., description="Board status id (a column, e.g. 'In Progress'). Resolve via list_board_statuses."
    )
    team_id: uuid.UUID = Field(..., description="Team the task belongs to. Resolve via list_teams.")
    assignee_ids: list[uuid.UUID] = Field(
        default_factory=list, description="User ids to assign. Resolve via list_workspace_people."
    )
    expected_completion: str | None = Field(None, description="ISO-8601 due date, e.g. '2026-09-15'.")
    progress: int = Field(0, ge=0, le=100, description="Completion percentage, 0-100.")


class GetTaskInput(CamelModel):
    """Arguments for fetching a single TaskFlow task by id."""

    task_id: uuid.UUID = Field(..., description="Unique identifier of the task to fetch.")


class ListTasksInput(CamelModel):
    """Arguments for listing/filtering TaskFlow tasks. Matches TaskController.GetTasks."""

    search: str | None = Field(None, description="Free-text search over task title/description.")
    team_id: uuid.UUID | None = Field(None, description="Filter by team.")
    status_id: uuid.UUID | None = Field(None, description="Filter by board status.")
    assignee_id: uuid.UUID | None = Field(None, description="Filter by assignee.")
    page: int = Field(1, ge=1, description="Page number, 1-indexed.")
    limit: int = Field(20, ge=1, le=200, description="Page size.")


class GetMyTasksInput(CamelModel):
    """Arguments for listing tasks assigned to the current user. Matches TaskController.GetMyTasks.

    Prefer this over `list_tasks` + client-side filtering when the question is
    about "my" tasks — it's a single, already-filtered backend call.
    """

    search: str | None = Field(None, description="Free-text search over task title/description.")
    team_id: uuid.UUID | None = Field(None, description="Filter by team.")
    page: int = Field(1, ge=1, description="Page number, 1-indexed.")
    limit: int = Field(20, ge=1, le=200, description="Page size.")


class GetBoardInput(CamelModel):
    """Arguments for fetching a team's full Kanban board in one call.

    Returns every board-status column together with its (non-deleted) tasks
    already grouped — prefer this over calling `list_board_statuses` then
    `list_tasks` per status and stitching them together yourself.
    """

    team_id: uuid.UUID = Field(..., description="Team whose board to fetch.")


class UpdateTaskInput(CamelModel):
    """Arguments for partially updating a TaskFlow task. Matches UpdateTaskRequestDto.

    Only the fields the caller actually sets are sent to the backend; every
    field besides `task_id` is optional.
    """

    task_id: uuid.UUID = Field(..., description="Unique identifier of the task to update.")
    title: str | None = Field(None, min_length=1, max_length=500, description="New title.")
    description: str | None = Field(None, description="New description.")
    priority: Priority | None = Field(None, description="New priority.")
    label: Label | None = Field(None, description="New label.")
    status_id: uuid.UUID | None = Field(None, description="New board status id (also how you change status).")
    assignee_ids: list[uuid.UUID] | None = Field(None, description="New full list of assignee user ids.")
    expected_completion: str | None = Field(None, description="New ISO-8601 due date.")
    progress: int | None = Field(None, ge=0, le=100, description="New completion percentage, 0-100.")

    def to_update_dict(self) -> dict:
        """Return only the fields the caller actually set, excluding `task_id`."""
        return self.model_dump(by_alias=True, exclude={"task_id"}, exclude_none=True, mode="json")


class DeleteTaskInput(CamelModel):
    """Arguments for deleting a TaskFlow task by id."""

    task_id: uuid.UUID = Field(..., description="Unique identifier of the task to delete.")


class ChangeTaskStatusInput(CamelModel):
    """Arguments for moving a task to a different board column. Matches TaskController.ChangeStatus."""

    task_id: uuid.UUID = Field(..., description="Task to move.")
    status_id: uuid.UUID = Field(..., description="Board status id to move the task into.")

    def to_body_dict(self) -> dict:
        return self.model_dump(by_alias=True, exclude={"task_id"}, mode="json")


# --- Board Statuses (BoardStatusController, /board-statuses) ---


class ListBoardStatusesInput(CamelModel):
    """Arguments for listing a team's board statuses (columns)."""

    team_id: uuid.UUID = Field(..., description="Team whose board statuses to list.")


class CreateBoardStatusInput(CamelModel):
    """Arguments for adding a custom board column to a team. Matches CreateBoardStatusRequestDto."""

    name: str = Field(..., min_length=1, description="Column name, e.g. 'Code Review'.")
    description: str | None = Field(None, description="Optional column description.")
    position: int = Field(..., ge=0, description="Column position; must not collide with an existing one.")
    team_id: uuid.UUID = Field(..., description="Team this column belongs to.")
    is_archivable: bool = Field(
        True,
        alias="isArchievable",  # sic — real (misspelled) wire field name, not a typo here.
        description="Whether tasks in this column are eligible for archival.",
    )


class DeleteBoardStatusInput(CamelModel):
    """Arguments for deleting a board column. Fails on the 3 seeded default columns (not deletable)."""

    status_id: uuid.UUID = Field(..., description="Board status (column) id to delete.")


# --- Teams (TeamController, /teams and /api/teams) ---


class ListTeamsInput(CamelModel):
    """Arguments for listing the current user's teams. Matches TeamController.GetMyTeams."""

    exclude_workspace: bool = Field(False, description="If true, exclude the implicit whole-workspace pseudo-team.")


class GetTeamInput(CamelModel):
    """Arguments for fetching a single team's full details."""

    team_id: uuid.UUID = Field(..., description="Team to fetch.")


class TeamMemberRole(CamelModel):
    """A (user, role) pair used when creating or updating a team's membership."""

    user_id: uuid.UUID = Field(..., description="Workspace member's user id.")
    role_id: uuid.UUID = Field(..., description="Role id from get_roles, e.g. Admin/PM/TL/Developer.")


class CreateTeamInput(CamelModel):
    """Arguments for creating a new team. Matches CreateTeamRequestDto.

    The caller is always auto-assigned the seeded Admin role on the new team;
    `member_ids` is for any *additional* members to add up front.
    """

    name: str = Field(..., min_length=1, description="Team name.")
    description: str | None = Field(None, description="Optional team description.")
    color: str | None = Field(None, description="Optional hex color, e.g. '#6155DD'.")
    member_ids: list[TeamMemberRole] = Field(
        default_factory=list, description="Additional members to add, each with a roleId from get_roles."
    )


class UpdateTeamInput(CamelModel):
    """Arguments for partially updating a team and/or syncing its membership. Requires the `Manage` permission.

    If `members` is set, it *replaces* the team's full member list — the team
    admin must be included or the backend rejects the request.
    """

    team_id: uuid.UUID = Field(..., description="Team to update.")
    name: str | None = Field(None, description="New team name.")
    description: str | None = Field(None, description="New description.")
    color: str | None = Field(None, description="New hex color.")
    members: list[TeamMemberRole] | None = Field(
        None, description="Full replacement member list (each with a roleId from get_roles)."
    )

    def to_update_dict(self) -> dict:
        return self.model_dump(by_alias=True, exclude={"team_id"}, exclude_none=True, mode="json")


class DeleteTeamInput(CamelModel):
    """Arguments for permanently deleting a team and all its associated data."""

    team_id: uuid.UUID = Field(..., description="Team to delete.")


class InviteToTeamInput(CamelModel):
    """Arguments for inviting a user to a specific team. Requires the `Manage` permission."""

    team_id: uuid.UUID = Field(..., description="Team to invite the user to.")
    email: EmailStr = Field(..., description="Invitee's email address.")
    role_id: uuid.UUID = Field(..., description="Role id from get_roles to assign on acceptance.")
    add_to_workspace: bool = Field(
        False, description="If true and the invitee isn't a workspace member yet, also add them to the workspace."
    )

    def to_body_dict(self) -> dict:
        return self.model_dump(by_alias=True, exclude={"team_id"}, mode="json")


class RemoveTeamMemberInput(CamelModel):
    """Arguments for removing a member from a team (not the whole workspace)."""

    team_id: uuid.UUID = Field(..., description="Team to remove the member from.")
    target_user_id: uuid.UUID = Field(..., description="User id of the member to remove.")


# --- Roles (RoleController) ---


class GetMyPermissionsInput(CamelModel):
    """Arguments for looking up the *caller's own* role/permissions on a team.

    Deliberately has no `userId` field: RoleController's `/permissions` route
    reads `userId` from a query parameter with no ownership check (an IDOR),
    so this tool always resolves "me" server-side from the caller's own
    token instead of trusting a model-supplied id.
    """

    team_id: uuid.UUID = Field(..., description="Team to check the caller's role/permissions on.")


# --- Workspace (WorkspaceController) ---


class GetWorkspaceInfoInput(CamelModel):
    """Arguments for fetching workspace details (owner, teams, members).

    `workspace_id` is optional — omit it to use the caller's own workspace
    (resolved from their token).
    """

    workspace_id: uuid.UUID | None = Field(None, description="Workspace to fetch; defaults to the caller's own.")


# --- People / workspace membership (PeopleController, /people) ---


class ListWorkspacePeopleInput(CamelModel):
    """Arguments for searching workspace members, to resolve a person's name/email to their user id."""

    search: str | None = Field(None, description="Free-text search over name/email.")
    team_id: uuid.UUID | None = Field(None, description="Filter to members of a specific team.")
    page: int = Field(1, ge=1, description="Page number, 1-indexed.")
    limit: int = Field(20, ge=1, le=200, description="Page size.")


class SendWorkspaceInvitationInput(CamelModel):
    """Arguments for inviting someone to the workspace by email."""

    email: EmailStr = Field(..., description="Email address to invite to the workspace.")


class UpdateWorkspaceMemberInput(CamelModel):
    """Arguments for updating a workspace member's details (e.g. their title)."""

    user_id: uuid.UUID = Field(..., description="Workspace member to update.")
    title: str | None = Field(None, description="New job title/role label to display for this member.")

    def to_update_dict(self) -> dict:
        return self.model_dump(by_alias=True, exclude={"user_id"}, exclude_none=True, mode="json")


class RemoveWorkspaceMemberInput(CamelModel):
    """Arguments for removing a member from the whole workspace (not just one team)."""

    user_id: uuid.UUID = Field(..., description="Workspace member to remove.")


class EnlistWorkspaceMembersInput(CamelModel):
    """Arguments for bulk-adding existing users as workspace members in one call."""

    user_ids: list[uuid.UUID] = Field(..., min_length=1, description="User ids to add to the workspace.")


class RespondToInvitationInput(CamelModel):
    """Arguments shared by accept/decline workspace invitation.

    Both ids are required explicitly: this backend endpoint is anonymous (a
    brand-new invitee may not have a session token yet), so there's no
    caller identity to resolve "me" from the way there is elsewhere.
    """

    workspace_id: uuid.UUID = Field(..., description="Workspace the invitation is for.")
    user_id: uuid.UUID = Field(..., description="User id responding to the invitation.")


class GetPendingInvitationsInput(CamelModel):
    """Arguments for listing a user's pending workspace invitations.

    `user_id` is optional — omit it to check the caller's own pending
    invitations (resolved from their token).
    """

    user_id: uuid.UUID | None = Field(None, description="User to check; defaults to the caller.")


# --- Users (UserController, /users and /api/users) ---


class ListUsersInput(CamelModel):
    """Arguments for listing users, optionally scoped to a workspace."""

    search: str | None = Field(None, description="Filter by name or email.")
    workspace_id: uuid.UUID | None = Field(
        None, description="Filter to users in a specific workspace; defaults to the caller's own workspace."
    )
    page: int = Field(1, ge=1, description="Page number, 1-indexed.")
    limit: int = Field(20, ge=1, le=200, description="Page size.")


class GetUserByIdInput(CamelModel):
    """Arguments for fetching a specific user's profile by id."""

    user_id: uuid.UUID = Field(..., description="User to fetch.")


class UpdateUserProfileInput(CamelModel):
    """Arguments for updating a user's profile. `user_id` defaults to the caller themself."""

    user_id: uuid.UUID | None = Field(None, description="User to update; defaults to the caller.")
    name: str | None = Field(None, description="New display name.")
    title: str | None = Field(None, description="New job title.")
    avatar_url: str | None = Field(None, description="New avatar image URL.")
    avatar_public_id: str | None = Field(None, description="New avatar's storage public id (Cloudinary).")

    def to_update_dict(self) -> dict:
        return self.model_dump(by_alias=True, exclude={"user_id"}, exclude_none=True, mode="json")


class GetUserSettingsInput(CamelModel):
    """Arguments for fetching a user's app settings. `user_id` defaults to the caller themself."""

    user_id: uuid.UUID | None = Field(None, description="User whose settings to fetch; defaults to the caller.")


class UpdateUserSettingsInput(CamelModel):
    """Arguments for updating a user's app settings. `user_id` defaults to the caller themself."""

    user_id: uuid.UUID | None = Field(None, description="User whose settings to update; defaults to the caller.")
    notifications: bool | None = Field(None, description="Enable/disable notifications.")
    theme: str | None = Field(None, description="UI theme, e.g. 'dark' or 'light'.")
    language: str | None = Field(None, description="UI language code, e.g. 'en'.")
    days_to_archive: int | None = Field(
        None,
        alias="daysToArchieve",  # sic — real (misspelled) wire field name, not a typo here.
        description="Days of inactivity before a task is auto-archived.",
    )

    def to_update_dict(self) -> dict:
        return self.model_dump(by_alias=True, exclude={"user_id"}, exclude_none=True, mode="json")


class UpdateUserPasswordInput(CamelModel):
    """Arguments for changing a user's password. `user_id` defaults to the caller themself."""

    user_id: uuid.UUID | None = Field(None, description="User whose password to change; defaults to the caller.")
    new_password: str = Field(..., min_length=1, description="New password.")
    confirm_password: str = Field(..., min_length=1, description="New password, repeated for confirmation.")

    def to_body_dict(self) -> dict:
        return self.model_dump(by_alias=True, exclude={"user_id"}, mode="json")


# Document export (`ExportDocumentInput`/`export_document`) deliberately does
# NOT live in this file — see `dedicated_tools/export_tool.py`'s module
# docstring. It's not a TaskFlow backend endpoint at all (no camelCase wire
# format needed), and it's registered as a plain LangChain tool directly in
# `agent/tools_registry.py` rather than through this MCP server.
