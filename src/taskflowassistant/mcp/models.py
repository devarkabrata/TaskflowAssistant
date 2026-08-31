"""Pydantic input schemas for each TaskFlow MCP tool.

Field names and types mirror the real .NET DTOs in
TaskFlowBackend/DTOs/Tasks, /Teams, /Workspaces exactly (see
TaskFlowBackend/Controllers/TaskController.cs, TeamController.cs,
BoardStatusController.cs, PeopleController.cs), so what the agent sends is
always valid without any translation layer.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

Priority = Literal["High", "Medium", "Low"]
Label = Literal["Feature", "Bug", "Design", "Docs", "Infra", "Refactor"]


class CreateTaskInput(BaseModel):
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


class GetTaskInput(BaseModel):
    """Arguments for fetching a single TaskFlow task by id."""

    task_id: uuid.UUID = Field(..., description="Unique identifier of the task to fetch.")


class ListTasksInput(BaseModel):
    """Arguments for listing/filtering TaskFlow tasks. Matches TaskController.GetTasks."""

    search: str | None = Field(None, description="Free-text search over task title.")
    team_id: uuid.UUID | None = Field(None, description="Filter by team.")
    status_id: uuid.UUID | None = Field(None, description="Filter by board status.")
    assignee_id: uuid.UUID | None = Field(None, description="Filter by assignee.")
    page: int = Field(1, ge=1, description="Page number, 1-indexed.")
    limit: int = Field(20, ge=1, le=200, description="Page size.")


class UpdateTaskInput(BaseModel):
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
        return self.model_dump(exclude={"task_id"}, exclude_none=True, mode="json")


class DeleteTaskInput(BaseModel):
    """Arguments for deleting a TaskFlow task by id."""

    task_id: uuid.UUID = Field(..., description="Unique identifier of the task to delete.")


class ListTeamsInput(BaseModel):
    """Arguments for listing the current user's teams. Matches TeamController.GetMyTeams."""

    exclude_workspace: bool = Field(
        False, description="If true, exclude the implicit whole-workspace pseudo-team."
    )


class ListBoardStatusesInput(BaseModel):
    """Arguments for listing a team's board statuses (columns)."""

    team_id: uuid.UUID = Field(..., description="Team whose board statuses to list.")


class ListWorkspacePeopleInput(BaseModel):
    """Arguments for searching workspace members, to resolve an assignee's user id."""

    search: str | None = Field(None, description="Free-text search over name/email.")
    page: int = Field(1, ge=1, description="Page number, 1-indexed.")
    limit: int = Field(20, ge=1, le=200, description="Page size.")


class SendWorkspaceInvitationInput(BaseModel):
    """Arguments for inviting someone to the workspace by email."""

    email: EmailStr = Field(..., description="Email address to invite to the workspace.")
