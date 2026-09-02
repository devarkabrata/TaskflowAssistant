def pick_first(source: dict, *keys: str):
    """Return the first present value among these key spellings (camelCase or PascalCase).

    Public (not underscore-prefixed) because `mcp/server.py` also uses this to
    pull an id out of the raw `/auth/me` payload when resolving "the caller"
    for self-scoped tools — see `_resolve_user_id`/`_resolve_workspace_id`.
    """
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return None


_pick = pick_first  # noqa: N816 - internal alias so this file's own call sites stay short.


def trim_result(result, item_fn):
    """Trim every record found in a list tool's result, whatever shape it comes in.

    Handles both a plain array (TeamController.GetMyTeams, BoardStatusController.GetCatalog)
    and a paged-result wrapper dict (TaskController.GetTasks, PeopleController.GetPeople) —
    for the latter, only the list-valued field(s) get trimmed, so `total`/`page`/`limit` etc.
    are left untouched.
    """
    if isinstance(result, list):
        return [item_fn(item) for item in result]
    if isinstance(result, dict):
        trimmed = dict(result)
        for key, value in result.items():
            if isinstance(value, list):
                trimmed[key] = [item_fn(item) for item in value]
        return trimmed
    return result


def trim_task(task: dict) -> dict:
    """Keep only what the agent needs from a task; drop timestamps/created-by/etc."""
    return {
        "id": _pick(task, "id", "Id"),
        "title": _pick(task, "title", "Title"),
        "priority": _pick(task, "priority", "Priority"),
        "label": _pick(task, "label", "Label"),
        "statusId": _pick(task, "statusId", "StatusId"),
        "status": _pick(task, "status", "Status"),
        "teamId": _pick(task, "teamId", "TeamId"),
        "assignees": [
            {"userId": _pick(a, "userId", "UserId"), "name": _pick(a, "name", "Name")}
            for a in (_pick(task, "assignees", "Assignees") or [])
        ],
        "expectedCompletion": _pick(task, "expectedCompletion", "ExpectedCompletion"),
        "progress": _pick(task, "progress", "Progress"),
    }


def trim_team(team: dict) -> dict:
    """Keep only what's needed to resolve a team name to its id."""
    return {
        "id": _pick(team, "id", "Id"),
        "name": _pick(team, "name", "Name"),
        "description": _pick(team, "description", "Description"),
    }


def trim_board_status(status: dict) -> dict:
    """Keep only what's needed to resolve a status/column name to its id."""
    return {
        "id": _pick(status, "id", "Id"),
        "name": _pick(status, "name", "Name"),
        "position": _pick(status, "position", "Position"),
    }


def trim_person(person: dict) -> dict:
    """Keep only what's needed to resolve a person's name/email to their user id."""
    return {
        "userId": _pick(person, "userId", "id", "UserId", "Id"),
        "name": _pick(person, "name", "Name"),
        "email": _pick(person, "email", "Email"),
        "status": _pick(person, "status", "Status"),
    }


def trim_user(user: dict) -> dict:
    """Keep only what's needed to resolve a user's name/email to their id."""
    return {
        "id": _pick(user, "id", "Id", "userId", "UserId"),
        "name": _pick(user, "name", "Name"),
        "email": _pick(user, "email", "Email"),
        "title": _pick(user, "title", "Title"),
    }


def trim_board(board) -> object:
    """Trim a Kanban board response: each status column keeps its tasks, trimmed via `trim_task`.

    Handles both a plain array of columns and a wrapper dict with a
    list-valued `columns`/`statuses` field.
    """

    def trim_column(column: dict) -> dict:
        tasks = _pick(column, "tasks", "Tasks") or []
        return {
            "id": _pick(column, "id", "Id"),
            "name": _pick(column, "name", "Name"),
            "position": _pick(column, "position", "Position"),
            "tasks": [trim_task(task) for task in tasks],
        }

    if isinstance(board, list):
        return [trim_column(column) for column in board]
    if isinstance(board, dict):
        trimmed = dict(board)
        for key in ("columns", "statuses", "Columns", "Statuses"):
            if isinstance(board.get(key), list):
                trimmed[key] = [trim_column(column) for column in board[key]]
        return trimmed
    return board