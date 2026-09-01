"""FastAPI app exposing the TaskFlow agent as a background-job chat endpoint.

POST /chat kicks off the agent in a background task and returns almost
instantly with a job_id — it does NOT hold the connection open for the
agent's whole run. GET /chat/{job_id} is polled by the client for progress.

Why: the deployed app sits behind Render's Cloudflare proxy, which enforces
a hard ~100s limit if the origin goes quiet — not configurable on Free/Pro/
Business plans. A multi-step tool-calling turn can genuinely run longer than
that. Rather than fight that limit at the transport level (heartbeats,
deadlines — tried, still fragile), no single HTTP request is ever held open
long enough for it to matter here.

Each job's events list uses the same shapes as before:
  - {"type": "tool_call",   "tool": ..., "args": ...}   agent decided to call a tool
  - {"type": "tool_result", "tool": ..., "output": ...} that tool's result came back
  - {"type": "token",       "content": ...}             a piece of the final answer
  - {"type": "error",       "message": ...}              something went wrong

Run with: uv run taskflow-agent
"""

import asyncio
import os
import sys
import time
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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


class ChatRequest(BaseModel):
    message: str
    thread_id: str


# In-memory job store: job_id -> {"status", "events", "created_at"}. Fine for
# this app's scale; a real multi-instance production deployment would need
# this backed by Redis/a DB instead so jobs survive across processes.
jobs: dict[str, dict] = {}
_JOB_TTL_SECONDS = 600


def _prune_old_jobs() -> None:
    """Drop finished jobs older than _JOB_TTL_SECONDS, so the store doesn't grow forever."""
    now = time.monotonic()
    stale = [
        job_id
        for job_id, job in jobs.items()
        if job["status"] != "running" and now - job["created_at"] > _JOB_TTL_SECONDS
    ]
    for job_id in stale:
        del jobs[job_id]


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


async def _run_agent_job(job_id: str, message: str, thread_id: str, taskflow_token: str) -> None:
    """Run the agent to completion, appending events to the job as they occur.

    Builds a fresh agent (and its MCP subprocess) for this one job, so the
    TaskFlow tools use *this caller's* token — not a shared one. The
    checkpointer (agent/memory.py) is a module-level singleton shared across
    jobs, so thread_id-based conversation history still works correctly even
    though the agent object itself is rebuilt each time.

    The 180s timeout here is just a safety net against genuinely hung work
    (a stuck backend call, a retry storm) — unlike the old SSE version,
    there's no client-facing connection to protect, so it's safe to just
    cancel the whole thing on timeout rather than needing to carefully avoid
    cancelling in-flight steps.
    """
    job = jobs[job_id]
    try:
        agent = await build_agent(taskflow_token=taskflow_token)

        async def consume() -> None:
            async for stream_mode, chunk in agent.astream(
                {"messages": [{"role": "user", "content": message}]},
                config={"configurable": {"thread_id": thread_id}},
                stream_mode=["messages", "updates"],
            ):
                if stream_mode == "updates":
                    if "model" in chunk:
                        for call in chunk["model"]["messages"][0].tool_calls:
                            job["events"].append(
                                {"type": "tool_call", "tool": call["name"], "args": call["args"]}
                            )
                    if "tools" in chunk:
                        for tool_message in chunk["tools"]["messages"]:
                            job["events"].append(
                                {
                                    "type": "tool_result",
                                    "tool": tool_message.name,
                                    "output": _extract_text(tool_message.content),
                                }
                            )
                elif stream_mode == "messages":
                    message_chunk, _metadata = chunk
                    # "messages" mode also carries ToolMessages (already
                    # reported via "tool_result" above) — only record actual
                    # AI text here. Note: AIMessageChunk.type ==
                    # "AIMessageChunk", NOT "ai" (that's only true for the
                    # full, non-streaming AIMessage) — isinstance is correct.
                    text = (
                        _extract_text(message_chunk.content)
                        if isinstance(message_chunk, AIMessageChunk)
                        else ""
                    )
                    if text:
                        job["events"].append({"type": "token", "content": text})

        await asyncio.wait_for(consume(), timeout=180)
        job["status"] = "done"
    except TimeoutError:
        job["events"].append(
            {
                "type": "error",
                "message": (
                    "This request took too long and was stopped. Please try again — "
                    "this can happen if an external call (e.g. the TaskFlow backend) is slow to respond."
                ),
            }
        )
        job["status"] = "error"
    except Exception as exc:
        job["events"].append({"type": "error", "message": str(exc)})
        job["status"] = "error"


@app.post("/chat")
async def chat(request: ChatRequest, authorization: str = Header(...)):
    """Kick off a chat turn in the background and return its job_id immediately.

    The `Authorization` header must carry the caller's real TaskFlow bearer
    token (`Bearer <jwt>`) — it's forwarded to the TaskFlow MCP tools so
    task/team data is scoped to whoever is actually asking, not a shared
    service account. Poll GET /chat/{job_id} for progress and the final result.
    """
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401, detail="Authorization header must be 'Bearer <token>'."
        )
    taskflow_token = authorization.split(" ", 1)[1]

    _prune_old_jobs()

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "events": [], "created_at": time.monotonic()}
    asyncio.create_task(_run_agent_job(job_id, request.message, request.thread_id, taskflow_token))

    return {"job_id": job_id}


@app.get("/chat/{job_id}")
async def chat_status(job_id: str) -> dict:
    """Poll a chat job's accumulated events and current status."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    return {"status": job["status"], "events": job["events"]}


@app.get("/health")
async def health() -> dict:
    """Health check for Render (and anything else pinging the service)."""
    return {"success": True, "message": "Taskflow Agent is UP and RUNNING..."}


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
