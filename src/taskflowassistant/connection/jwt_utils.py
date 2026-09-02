"""Reads claims out of the TaskFlow access token without verifying its signature.

Verification is the backend's job — every call using these claims still goes
out with the same bearer token attached, so the backend rejects it if it's
invalid or expired. We only decode the payload locally to resolve "me" (the
caller's own user id) for tools that must never accept a caller-supplied user
id for someone else — see `mcp/server.py`'s `get_my_permissions`, which exists
specifically to avoid the IDOR in RoleController's `/permissions` endpoint
(it takes `userId` from a query string with no ownership check).

.NET's default JWT bearer handler maps the standard `sub` claim onto the long
`ClaimTypes.NameIdentifier` URI, so real TaskFlow tokens may carry either
spelling depending on how the handler is configured — both are checked here.
"""

import base64
import json

_USER_ID_CLAIMS = (
    "sub",
    "userId",
    "user_id",
    "nameid",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier",
)
_WORKSPACE_ID_CLAIMS = ("workspaceId", "workspace_id", "wsId")


def _decode_claims(token: str) -> dict:
    """Decode a JWT's payload segment into a dict, without checking its signature."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Not a JWT (expected 3 dot-separated segments).")
    payload = parts[1]
    padded = payload + "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def _first_claim(token: str, keys: tuple[str, ...]) -> str | None:
    try:
        claims = _decode_claims(token)
    except (ValueError, json.JSONDecodeError):
        return None
    for key in keys:
        value = claims.get(key)
        if value:
            return str(value)
    return None


def current_user_id(token: str | None) -> str | None:
    """Best-effort extraction of the caller's own user id from their bearer token."""
    if not token:
        return None
    return _first_claim(token, _USER_ID_CLAIMS)


def current_workspace_id(token: str | None) -> str | None:
    """Best-effort extraction of the caller's workspace id from their bearer token."""
    if not token:
        return None
    return _first_claim(token, _WORKSPACE_ID_CLAIMS)
