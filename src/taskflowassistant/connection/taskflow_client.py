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

    # --- Task CRUD (TaskController,/tasks) ---

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

    # --- Lookups, so the agent can resolve names to the GUIDs the API needs ---

    async def list_teams(self, exclude_workspace: bool = False) -> Any:
        """GET /teams (TeamController.GetMyTeams)"""
        client = self._require_client()
        response = await client.get("/teams", params={"exclude_workspace": exclude_workspace})
        return _unwrap(response)

    async def list_board_statuses(self, team_id: uuid.UUID | str) -> Any:
        """GET /board-statuses/team/{teamId} (BoardStatusController.GetCatalog)"""
        client = self._require_client()
        response = await client.get(f"/board-statuses/team/{team_id}")
        return _unwrap(response)

    async def list_workspace_people(
        self, search: str | None = None, page: int = 1, limit: int = 20
    ) -> Any:
        """GET /people (PeopleController.GetPeople)"""
        client = self._require_client()
        params: dict[str, Any] = {"page": page, "limit": limit}
        if search:
            params["search"] = search
        response = await client.get("/people", params=params)
        return _unwrap(response)

    # --- Invitation (PeopleController) ---

    async def send_workspace_invitation(self, email: str) -> Any:
        """POST /people/invite"""
        client = self._require_client()
        response = await client.post("/people/invite", json={"email": email})
        return _unwrap(response)
