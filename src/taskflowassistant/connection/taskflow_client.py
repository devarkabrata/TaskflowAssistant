"""Async HTTP client for the TaskFlow backend REST API.

Plain HTTP concerns only — no MCP or LangChain imports belong in this file.
`mcp/server.py` calls these methods; it never builds requests itself.

Every response from the backend is wrapped in the same envelope
(TaskFlowBackend/Helpers/ApiResponse.cs):

    {"status": true, "code": 200, "result": {...}, "message": "...", "errors": [...], ...}

`_unwrap()` below is the one place that understands that envelope.
"""

import uuid
from typing import Any

import httpx

from taskflowassistant.connection.config import config


class TaskFlowAPIError(Exception):
    """Raised when the TaskFlow backend responds with status: false."""

    def __init__(self, message: str, errors: list | None = None) -> None:
        self.message = message
        self.errors = errors or []
        super().__init__(message)


def _unwrap(response: httpx.Response) -> Any:
    """Pull the real payload out of the backend's ApiResponse envelope."""
    response.raise_for_status()
    body = response.json()
    if not body.get("status", True):
        raise TaskFlowAPIError(body.get("message", "TaskFlow API request failed."), body.get("errors"))
    return body.get("result")


class TaskFlowClient:
    """Thin async wrapper around the TaskFlow backend's REST endpoints.

    Usage:
        async with TaskFlowClient() as client:
            task = await client.create_task({...})
    """

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self._base_url = (base_url or config["TASKFLOW_API_BASE_URL"]).rstrip("/")
        self._token = token if token is not None else config["TASKFLOW_API_TOKEN"]
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def __aenter__(self) -> "TaskFlowClient":
        self._client = httpx.AsyncClient(base_url=self._base_url, headers=self._headers(), timeout=30.0)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "TaskFlowClient must be used as an async context manager, "
                "e.g. `async with TaskFlowClient() as client: ...`"
            )
        return self._client

    # --- Task CRUD (TaskController, /tasks) ---

    async def create_task(self, task: dict[str, Any]) -> Any:
        """POST /tasks"""
        client = self._require_client()
        response = await client.post("/tasks", json=task)
        return _unwrap(response)

    async def get_task(self, task_id: uuid.UUID | str) -> Any:
        """GET /tasks/{id}"""
        client = self._require_client()
        response = await client.get(f"/tasks/{task_id}")
        return _unwrap(response)

    async def list_tasks(self, params: dict[str, Any] | None = None) -> Any:
        """GET /tasks"""
        client = self._require_client()
        response = await client.get("/tasks", params=params or {})
        return _unwrap(response)

    async def get_my_tasks(self, params: dict[str, Any] | None = None) -> Any:
        """GET /tasks/my (TaskController.GetMyTasks) — same shape as GetTasks, implicitly assignee=self."""
        client = self._require_client()
        response = await client.get("/tasks/my", params=params or {})
        return _unwrap(response)

    async def get_board(self, team_id: uuid.UUID | str) -> Any:
        """GET /tasks/team/{teamId}/board (TaskController.GetBoard) — full Kanban board in one call."""
        client = self._require_client()
        response = await client.get(f"/tasks/team/{team_id}/board")
        return _unwrap(response)

    async def update_task(self, task_id: uuid.UUID | str, updates: dict[str, Any]) -> Any:
        """PUT /tasks/{id}"""
        client = self._require_client()
        response = await client.put(f"/tasks/{task_id}", json=updates)
        return _unwrap(response)

    async def delete_task(self, task_id: uuid.UUID | str) -> Any:
        """DELETE /tasks/{id}"""
        client = self._require_client()
        response = await client.delete(f"/tasks/{task_id}")
        return _unwrap(response)

    async def change_task_status(self, task_id: uuid.UUID | str, body: dict[str, Any]) -> Any:
        """PATCH /tasks/{id}/status"""
        client = self._require_client()
        response = await client.patch(f"/tasks/{task_id}/status", json=body)
        return _unwrap(response)

    # --- Board Statuses (BoardStatusController, /board-statuses) ---

    async def list_board_statuses(self, team_id: uuid.UUID | str) -> Any:
        """GET /board-statuses/team/{teamId} (BoardStatusController.GetCatalog)"""
        client = self._require_client()
        response = await client.get(f"/board-statuses/team/{team_id}")
        return _unwrap(response)

    async def create_board_status(self, status: dict[str, Any]) -> Any:
        """POST /board-statuses/create"""
        client = self._require_client()
        response = await client.post("/board-statuses/create", json=status)
        return _unwrap(response)

    async def delete_board_status(self, status_id: uuid.UUID | str) -> Any:
        """DELETE /board-statuses/{statusId}"""
        client = self._require_client()
        response = await client.delete(f"/board-statuses/{status_id}")
        return _unwrap(response)

    # --- Teams (TeamController) ---
    # NOTE: GetMyTeams really is at `/teams` with no `/api` prefix, unlike
    # every other Teams endpoint below — confirmed against the live
    # collection, not a typo here.

    async def list_teams(self, exclude_workspace: bool = False) -> Any:
        """GET /teams (TeamController.GetMyTeams)"""
        client = self._require_client()
        response = await client.get("/teams", params={"exclude_workspace": exclude_workspace})
        return _unwrap(response)

    async def get_team(self, team_id: uuid.UUID | str) -> Any:
        """GET /api/teams/{teamId}"""
        client = self._require_client()
        response = await client.get(f"/api/teams/{team_id}")
        return _unwrap(response)

    async def get_team_stats(self) -> Any:
        """GET /api/teams/stats"""
        client = self._require_client()
        response = await client.get("/api/teams/stats")
        return _unwrap(response)

    async def create_team(self, team: dict[str, Any]) -> Any:
        """POST /api/teams"""
        client = self._require_client()
        response = await client.post("/api/teams", json=team)
        return _unwrap(response)

    async def update_team(self, team_id: uuid.UUID | str, updates: dict[str, Any]) -> Any:
        """PUT /api/teams/{teamId}"""
        client = self._require_client()
        response = await client.put(f"/api/teams/{team_id}", json=updates)
        return _unwrap(response)

    async def delete_team(self, team_id: uuid.UUID | str) -> Any:
        """DELETE /api/teams/{teamId}"""
        client = self._require_client()
        response = await client.delete(f"/api/teams/{team_id}")
        return _unwrap(response)

    async def invite_to_team(self, team_id: uuid.UUID | str, body: dict[str, Any]) -> Any:
        """POST /api/teams/{teamId}/invite — requires the caller's role to have `Manage`."""
        client = self._require_client()
        response = await client.post(f"/api/teams/{team_id}/invite", json=body)
        return _unwrap(response)

    async def remove_team_member(self, team_id: uuid.UUID | str, target_user_id: uuid.UUID | str) -> Any:
        """DELETE /api/teams/{teamId}/members/{targetUserId}"""
        client = self._require_client()
        response = await client.delete(f"/api/teams/{team_id}/members/{target_user_id}")
        return _unwrap(response)

    # --- Roles (RoleController) ---
    # NOTE: both routes below deviate from the `/api/roles` convention their
    # controller's class-level [Route] implies — confirmed against the live
    # collection. `/permissions` in particular is an absolute route override.

    async def get_roles(self) -> Any:
        """GET /roles"""
        client = self._require_client()
        response = await client.get("/roles")
        return _unwrap(response)

    async def get_permissions(self, team_id: uuid.UUID | str, user_id: uuid.UUID | str) -> Any:
        """GET /permissions?teamId=&userId= — caller-facing tools must always pass their OWN user_id.

        The backend takes `userId` from the query string with no ownership
        check (an IDOR); this client method still takes an explicit
        `user_id` for testability, but `mcp/server.py`'s `get_my_permissions`
        tool never lets that value come from the model — it resolves the
        caller's own id from their token first. Don't add a tool that forwards
        an arbitrary caller-supplied user_id here.
        """
        client = self._require_client()
        response = await client.get("/permissions", params={"teamId": str(team_id), "userId": str(user_id)})
        return _unwrap(response)

    # --- Workspace (WorkspaceController) ---

    async def get_workspace_info(self, workspace_id: uuid.UUID | str) -> Any:
        """GET /api/workspace/{workspaceId}/info"""
        client = self._require_client()
        response = await client.get(f"/api/workspace/{workspace_id}/info")
        return _unwrap(response)

    # --- People / workspace membership (PeopleController, /people) ---

    async def list_workspace_people(self, params: dict[str, Any] | None = None) -> Any:
        """GET /people"""
        client = self._require_client()
        response = await client.get("/people", params=params or {})
        return _unwrap(response)

    async def get_workspace_stats(self) -> Any:
        """GET /people/stats"""
        client = self._require_client()
        response = await client.get("/people/stats")
        return _unwrap(response)

    async def send_workspace_invitation(self, email: str) -> Any:
        """POST /people/invite"""
        client = self._require_client()
        response = await client.post("/people/invite", json={"email": email})
        return _unwrap(response)

    async def update_workspace_member(self, user_id: uuid.UUID | str, updates: dict[str, Any]) -> Any:
        """PATCH /people/{userId}"""
        client = self._require_client()
        response = await client.patch(f"/people/{user_id}", json=updates)
        return _unwrap(response)

    async def remove_workspace_member(self, user_id: uuid.UUID | str) -> Any:
        """DELETE /people/{userId}"""
        client = self._require_client()
        response = await client.delete(f"/people/{user_id}")
        return _unwrap(response)

    async def enlist_workspace_members(self, user_ids: list[str]) -> Any:
        """POST /people/enlist"""
        client = self._require_client()
        response = await client.post("/people/enlist", json={"userIds": user_ids})
        return _unwrap(response)

    async def accept_workspace_invitation(self, body: dict[str, Any]) -> Any:
        """POST /people/invitations/accept — anonymous endpoint (no auth required)."""
        client = self._require_client()
        response = await client.post("/people/invitations/accept", json=body)
        return _unwrap(response)

    async def decline_workspace_invitation(self, body: dict[str, Any]) -> Any:
        """POST /people/invitations/decline — anonymous endpoint (no auth required)."""
        client = self._require_client()
        response = await client.post("/people/invitations/decline", json=body)
        return _unwrap(response)

    async def get_pending_invitations(self, user_id: uuid.UUID | str) -> Any:
        """GET /people/invitations?userId="""
        client = self._require_client()
        response = await client.get("/people/invitations", params={"userId": str(user_id)})
        return _unwrap(response)

    # --- Users (UserController) ---
    # NOTE: `update_user` really is under `/api/users/{id}`; every other
    # Users endpoint below has no `/api` prefix — confirmed against the live
    # collection, not a typo here.

    async def list_users(self, params: dict[str, Any] | None = None) -> Any:
        """GET /users"""
        client = self._require_client()
        response = await client.get("/users", params=params or {})
        return _unwrap(response)

    async def get_user_by_id(self, user_id: uuid.UUID | str) -> Any:
        """GET /users/{userId}"""
        client = self._require_client()
        response = await client.get(f"/users/{user_id}")
        return _unwrap(response)

    async def update_user_profile(self, user_id: uuid.UUID | str, updates: dict[str, Any]) -> Any:
        """PUT /api/users/{userId}"""
        client = self._require_client()
        response = await client.put(f"/api/users/{user_id}", json=updates)
        return _unwrap(response)

    async def get_user_settings(self, user_id: uuid.UUID | str) -> Any:
        """GET /users/{userId}/settings"""
        client = self._require_client()
        response = await client.get(f"/users/{user_id}/settings")
        return _unwrap(response)

    async def update_user_settings(self, user_id: uuid.UUID | str, updates: dict[str, Any]) -> Any:
        """PUT /users/{userId}/settings"""
        client = self._require_client()
        response = await client.put(f"/users/{user_id}/settings", json=updates)
        return _unwrap(response)

    async def update_user_password(self, user_id: uuid.UUID | str, body: dict[str, Any]) -> Any:
        """PUT /users/{userId}/password"""
        client = self._require_client()
        response = await client.put(f"/users/{user_id}/password", json=body)
        return _unwrap(response)
