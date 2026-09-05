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
import time

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools as _load_tools_from_session

from taskflowassistant.connection.config import config

_SERVER_NAME = "taskflow"

# How long a caller's cached MCP session may sit unused before it's closed.
# Reuse across messages in the same conversation is the whole point of the
# cache below; this bound just stops a departed caller's session (and, for
# stdio, its subprocess) from living forever.
_IDLE_TTL_SECONDS = 600


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
    """

    def __init__(self, taskflow_token: str | None):
        self.tools: list[BaseTool] | None = None
        self.error: BaseException | None = None
        self.last_used = time.monotonic()
        self._ready = asyncio.Event()
        self._close_requested = asyncio.Event()
        self.task = asyncio.create_task(self._run(taskflow_token))

    async def _run(self, taskflow_token: str | None) -> None:
        client = MultiServerMCPClient(_build_connection(taskflow_token))
        try:
            async with client.session(_SERVER_NAME) as session:
                self.tools = await _load_tools_from_session(session, server_name=_SERVER_NAME)
                self._ready.set()
                while True:
                    try:
                        await asyncio.wait_for(self._close_requested.wait(), timeout=30)
                        break
                    except TimeoutError:
                        if time.monotonic() - self.last_used > _IDLE_TTL_SECONDS:
                            break
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
        self.last_used = time.monotonic()
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
    A session that's gone idle for `_IDLE_TTL_SECONDS`, or that failed, is
    dropped and rebuilt on the next call.
    """
    key = taskflow_token or "__default__"
    session = _sessions.get(key)
    if session is None or not session.is_alive():
        session = _CachedSession(taskflow_token)
        _sessions[key] = session
    return await session.get_tools()


async def close_all_mcp_sessions() -> None:
    """Close every cached session's background task and wait for it to exit.

    Call this on app shutdown so a stdio session's subprocess is torn down
    cleanly instead of potentially outliving the process.
    """
    sessions = list(_sessions.values())
    for session in sessions:
        session.close()
    await asyncio.gather(*(s.task for s in sessions), return_exceptions=True)
