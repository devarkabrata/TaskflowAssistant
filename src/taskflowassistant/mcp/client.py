"""Loads the TaskFlow MCP server's tools into LangChain via langchain-mcp-adapters.

Two transports are supported (via connection.config.config["MCP_TRANSPORT"]):
- "stdio": this process spawns `python -m taskflowassistant.mcp.server` itself.
- "streamable_http": this process connects to an already-running server over HTTP.
"""

import os
import sys

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

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
        # Per-request override: this subprocess is spawned fresh for this one
        # request, so its TaskFlow tools act as *this caller*, not whichever
        # static token is in .env.
        env["TASKFLOW_API_TOKEN"] = taskflow_token
    return {
        _SERVER_NAME: {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "taskflowassistant.mcp.server"],
            "env": env,
        }
    }


async def load_mcp_tools(taskflow_token: str | None = None) -> list[BaseTool]:
    """Connect to the TaskFlow MCP server and return its tools as LangChain tools.

    `taskflow_token`, if given, overrides the spawned server's TASKFLOW_API_TOKEN
    so its tools act on behalf of whoever is actually making this request.
    """
    client = MultiServerMCPClient(_build_connection(taskflow_token))
    return await client.get_tools(server_name=_SERVER_NAME)
