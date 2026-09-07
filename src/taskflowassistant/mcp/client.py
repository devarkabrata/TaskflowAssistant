"""Loads the TaskFlow MCP server's tools into LangChain via langchain-mcp-adapters.

Two transports are supported (via connection.config.config["MCP_TRANSPORT"]):
- "stdio": this process spawns `python -m taskflowassistant.mcp.server` itself.
- "streamable_http": this process connects to an already-running server over HTTP.

`MultiServerMCPClient.get_tools()` looks like it reuses one connection, but it
doesn't: every tool it returns calls `load_mcp_tools(None, connection=...)`
under the hood, so each individual tool invocation opens (and tears down) its
own fresh session — for "stdio" that means spawning a brand-new subprocess
and redoing the MCP handshake on every single tool call, not just once per
message. `load_mcp_tools` below avoids that by holding on to one real
`ClientSession` per caller (via `client.session(...)`) and building the
LangChain tools from THAT session, so every tool call reuses it instead.
"""

import asyncio
import os
import sys

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools as _load_tools_from_session

from taskflowassistant.connection.config import config

_SERVER_NAME = "taskflow"


def _build_connection(taskflow_token: str | None = None) -> dict:
    if config["MCP_TRANSPORT"] == "streamable_http":
        return {
            _SERVER_NAME: {
                "transport": "streamable_http",
                "url": config["MCP_SERVER_URL"],
            }
        }
    # stdio_client only forwards a minimal default environment unless told
    # otherwise — pass the real one through so the spawned server can still
    # read GEMINI_*/TASKFLOW_* from the shell env.
    env = dict(os.environ)
    if taskflow_token:
        # Per-caller override: this session is scoped to one caller (see
        # `load_mcp_tools`'s cache key below), so its TaskFlow tools act as
        # *that caller*, not whichever static token is in .env.
        env["TASKFLOW_API_TOKEN"] = taskflow_token
    return {
        _SERVER_NAME: {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "taskflowassistant.mcp.server"],
            "env": env,
        }
    }


class _CachedSession:
    """Owns one live MCP session, kept open by a dedicated background task.

    anyio's stdio transport ties its cancel scope to the asyncio Task that
    opened it, so the `async with client.session(...)` block below must be
    entered AND exited from the same Task — it can't be opened for one
    request and closed by another. This background task holds that block
    open across every call that shares its cache key (see `load_mcp_tools`),
    and is the only thing that ever closes it.

    Deliberately no idle timeout: `graph_executor.py`'s compiled-graph cache
    holds onto these `tools` objects (bound into a `ToolNode`) for as long as
    that cache entry lives, with no way to know when this session under it
    gets torn down. An idle-based close here previously left that cache
    holding tools wired to an already-closed session — the next tool call
    through it hit a write on a closed stream (`anyio.ClosedResourceError`)
    instead of a clean rebuild. Only an explicit `close()` (app shutdown)
    ends this now.
    """

    def __init__(self, taskflow_token: str | None):
        self.tools: list[BaseTool] | None = None
        self.error: BaseException | None = None
        self._ready = asyncio.Event()
        self._close_requested = asyncio.Event()
        self.task = asyncio.create_task(self._run(taskflow_token))

    async def _run(self, taskflow_token: str | None) -> None:
        client = MultiServerMCPClient(_build_connection(taskflow_token))
        if config["MCP_TRANSPORT"] != "streamable_http":
            # Only stdio actually forks a new OS subprocess here — logged so
            # subprocess-count growth (e.g. many distinct callers, or one
            # respawning after a crash) is visible without attaching a
            # debugger.
            print(f"[mcp] spawning new MCP subprocess (key={taskflow_token or '__default__'!r})")
        try:
            async with client.session(_SERVER_NAME) as session:
                self.tools = await _load_tools_from_session(session, server_name=_SERVER_NAME)
                self._ready.set()
                await self._close_requested.wait()
        except Exception as exc:  # noqa: BLE001 - surfaced to waiters via `get_tools`
            self.error = exc
        finally:
            self._ready.set()

    def is_alive(self) -> bool:
        return not self.task.done()

    def close(self) -> None:
        self._close_requested.set()

    async def get_tools(self) -> list[BaseTool]:
        await self._ready.wait()
        if self.error is not None:
            raise self.error
        return self.tools


# One cached session per caller (keyed by their taskflow_token, so tool
# scoping stays per-caller exactly as before) — not a single global session.
# Safe without a lock: everything between the dict lookup and the dict store
# below is synchronous (no `await`), so no other asyncio Task can interleave
# and race the same key.
_sessions: dict[str, _CachedSession] = {}


async def load_mcp_tools(taskflow_token: str | None = None) -> list[BaseTool]:
    """Return this caller's TaskFlow MCP tools, reusing a live session across calls.

    `taskflow_token`, if given, scopes the session (and, for stdio, its
    subprocess) to whoever is actually making these requests, and doubles as
    the cache key: every message from the same caller reuses the same
    connection instead of paying for a brand-new one, while a different
    token naturally gets its own session rather than reusing someone else's.
    A session that has failed, or was explicitly closed (see
    `close_all_mcp_sessions`), is dropped and rebuilt on the next call. A
    session is otherwise kept open indefinitely — see `_CachedSession`'s
    docstring for why it can't be closed on an idle timer.
    """
    key = taskflow_token or "__default__"
    session = _sessions.get(key)
    if session is None or not session.is_alive():
        session = _CachedSession(taskflow_token)
        _sessions[key] = session
    return await session.get_tools()


def is_session_alive(taskflow_token: str | None = None) -> bool:
    """Whether this caller's cached MCP session is still alive.

    `graph_executor.py`'s compiled-graph cache holds a `ToolNode` built from
    a past `load_mcp_tools()` call's tool objects, which stay bound to
    whatever `_CachedSession` was live at that moment. That session no
    longer being reaped on an idle timer (see `_CachedSession`'s docstring)
    doesn't rule out it dying some other way — the MCP subprocess crashing,
    the connection dropping — after that graph was compiled and cached. This
    lets a cache hit there confirm the session it was built on is still the
    one running before trusting it, instead of only finding out via
    `anyio.ClosedResourceError` on the next tool call.

    Returns `False` (never alive) for a token with no cached session yet —
    correct for the caller either way: nothing to trust, so it should treat
    this like a dead session and (re)build one via `load_mcp_tools`.
    """
    session = _sessions.get(taskflow_token or "__default__")
    return session is not None and session.is_alive()


async def close_all_mcp_sessions() -> None:
    """Close every cached session's background task and wait for it to exit.

    Call this on app shutdown so a stdio session's subprocess is torn down
    cleanly instead of potentially outliving the process.
    """
    sessions = list(_sessions.values())
    for session in sessions:
        session.close()
    await asyncio.gather(*(s.task for s in sessions), return_exceptions=True)
