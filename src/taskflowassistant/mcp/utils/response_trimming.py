def _pick(source: dict, *keys: str):
    """Return the first present value among these key spellings (camelCase or PascalCase)."""
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return None


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