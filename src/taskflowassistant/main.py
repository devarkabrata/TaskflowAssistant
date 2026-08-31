"""FastAPI app exposing the TaskFlow agent as a streaming chat endpoint.

POST /chat streams the agent's response as Server-Sent Events (SSE). Each
line is `data: {...}\\n\\n`, where the JSON payload is one of:
  - {"type": "tool_call",   "tool": ..., "args": ...}   agent decided to call a tool
  - {"type": "tool_result", "tool": ..., "output": ...} that tool's result came back
  - {"type": "token",       "content": ...}             a piece of the final answer
  - {"type": "done"}                                    stream finished
  - {"type": "error",       "message": ...}              something went wrong

Run with: uv run taskflow-agent
"""

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessageChunk
from pydantic import BaseModel

from taskflowassistant.agent.executor import build_agent

app = FastAPI(title="TaskFlow Agent")

# Permissive for now — this is a test/dev CORS policy so a plain local HTML
# page (or any frontend) can call this API directly from the browser.
# Tighten allow_origins to the real frontend's domain before this is used
# for anything beyond testing.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    """Health check for Render (and anything else pinging the service)."""
    return {"status": "ok"}


class ChatRequest(BaseModel):
    message: str
    thread_id: str


def _extract_text(content) -> str:
    """LangChain message content is either a plain string or a list of
    content blocks (Gemini's format) — normalize either to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _sse(event: dict) -> str:
    """Format one event as a Server-Sent Events data line."""
    return f"data: {json.dumps(event)}\n\n"


async def _stream_agent_response(
    message: str, thread_id: str, taskflow_token: str
) -> AsyncIterator[str]:
    """Run the agent and yield SSE-formatted events as it works.

    Builds a fresh agent (and its MCP subprocess) for this one request, so
    the TaskFlow tools use *this caller's* token — not a shared one. The
    checkpointer (agent/memory.py) is a module-level singleton shared across
    requests, so thread_id-based conversation history still works correctly
    even though the agent object itself is rebuilt each time.
    """
    try:
        agent = await build_agent(taskflow_token=taskflow_token)

        async for stream_mode, chunk in agent.astream(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode=["messages", "updates"],
        ):
            if stream_mode == "updates":
                if "model" in chunk:
                    for call in chunk["model"]["messages"][0].tool_calls:
                        yield _sse(
                            {"type": "tool_call", "tool": call["name"], "args": call["args"]}
                        )
                if "tools" in chunk:
                    for tool_message in chunk["tools"]["messages"]:
                        yield _sse(
                            {
                                "type": "tool_result",
                                "tool": tool_message.name,
                                "output": _extract_text(tool_message.content),
                            }
                        )
            elif stream_mode == "messages":
                message_chunk, _metadata = chunk
                # "messages" mode also carries ToolMessages (already reported
                # via "tool_result" above) — only stream actual AI text here.
                # Note: AIMessageChunk.type == "AIMessageChunk", NOT "ai"
                # (that's only true for the full, non-streaming AIMessage) —
                # isinstance is the correct check here.
                text = (
                    _extract_text(message_chunk.content)
                    if isinstance(message_chunk, AIMessageChunk)
                    else ""
                )
                if text:
                    yield _sse({"type": "token", "content": text})

        yield _sse({"type": "done"})
    except Exception as exc:
        yield _sse({"type": "error", "message": str(exc)})


@app.post("/chat")
async def chat(request: ChatRequest, authorization: str = Header(...)):
    """Stream a chat response from the TaskFlow agent.

    The `Authorization` header must carry the caller's real TaskFlow bearer
    token (`Bearer <jwt>`) — it's forwarded to the TaskFlow MCP tools so
    task/team data is scoped to whoever is actually asking, not a shared
    service account.
    """
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401, detail="Authorization header must be 'Bearer <token>'."
        )
    taskflow_token = authorization.split(" ", 1)[1]

    return StreamingResponse(
        _stream_agent_response(request.message, request.thread_id, taskflow_token),
        media_type="text/event-stream",
    )


def run() -> None:
    """Sync entry point for the `taskflow-agent` console script — runs the API server."""
    import uvicorn

    loop = "auto"
    if sys.platform == "win32":
        # psycopg's async mode (used by the RAG retriever tool) can't run
        # under Windows' default ProactorEventLoop — it needs SelectorEventLoop.
        loop = asyncio.SelectorEventLoop
        sys.stdout.reconfigure(encoding="utf-8")

    # Render (and most PaaS platforms) assign the port dynamically via the
    # PORT env var and route to 0.0.0.0 — a hardcoded 127.0.0.1:8000 would be
    # unreachable there. Falls back to 127.0.0.1:8000 for local dev.
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host=host, port=port, loop=loop)


if __name__ == "__main__":
    run()
