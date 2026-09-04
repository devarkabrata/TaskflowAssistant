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

Each job's events list uses the following shapes:
  - {"type": "tool_call",   "tool": ..., "args": ...}   agent decided to call a tool
  - {"type": "tool_result", "tool": ..., "output": ...} that tool's result came back
  - {"type": "file",        "filename": ..., "url": ...} export_document produced a
                                                          document — render as a download
                                                          link/button, GET {url} to fetch it
  - {"type": "reasoning",   "content": ...}             text from a step that went on to
                                                          call a tool — the model "thinking
                                                          out loud", not the answer
  - {"type": "token",       "content": ...}             text from the final, no-more-tool-
                                                          calls step — the actual answer
  - {"type": "error",       "message": ...}              something went wrong
  - {"type": "stopped",     "message": ...}              POST /chat/{job_id}/stop aborted
                                                          this turn — a deliberate action,
                                                          not a failure; render distinctly
                                                          from "error"

A job's top-level "status" is one of "running", "done", "error", or
"cancelled" (set via POST /chat/{job_id}/stop) — stop polling once it's
anything other than "running".

The agent itself is a hand-built LangGraph `StateGraph` (see
`agent/graph_executor.py`), not LangChain's `create_agent` — this module was
migrated off `create_agent` and its middleware system, and later split into a
supervisor + domain-specialist multi-agent design (one small tool-bound
model per domain instead of one model bound to all ~40 tools — see
`agent/flow_nodes/supervisor.py`). Consequences that shape the streaming
code below:
  - There is no single "agent" node anymore — `agent/graph_executor.py`'s
    `SPECIALIST_NODE_NAMES` names one model-invoking node per domain (e.g.
    "task_agent", "team_agent", ...). The supervisor picks exactly one to
    start (its only routing call per turn — see flow_nodes/supervisor.py),
    but a specialist can explicitly hand off to another domain via a real
    `handoff_to_X` tool call (agent/handoff_tools.py), so more than one of
    these node names can run across a single turn — just never more than
    one AT a time, so at most one is ever present in a given "updates" chunk.
  - The "supervisor" node's own update (just a routing decision, no
    `messages` key) is deliberately not handled below — it's internal
    bookkeeping the user should never see, the same as "summarize"'s.
  - `create_agent`'s middleware system used to tag its summarizer's own model
    call as "internal" so it never leaked into the `messages` stream (see
    `langchain.agents.middleware.internal_call_transformer`). A hand-built
    graph has no such mechanism, so `agent/flow_nodes/summarizer.py`'s own
    `summarizer_model.ainvoke(...)` call streams through `stream_mode=
    "messages"` exactly like a specialist's — the only way to tell them
    apart is `metadata["langgraph_node"]`, which is why every chunk below is
    filtered on that before being buffered.

Run with: uv run taskflow-agent
"""

import asyncio
import json
import os
import re
import sys
import time
import uuid
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from langchain_core.exceptions import ModelError
from langchain_core.messages import AIMessageChunk
from pydantic import BaseModel
from starlette.background import BackgroundTask

from taskflowassistant.agent.graph_executor import (
    SPECIALIST_NODE_NAMES,
    SPECIALIST_TOOL_NODE_NAMES,
    build_compiled_graph,
)
from taskflowassistant.connection.config import config
from taskflowassistant.dedicated_tools.store import get_file, release_file

# The set of model-invoking / tool-executing node names in the current graph
# (one pair per domain specialist) — see graph_executor.py and this module's
# docstring.
_SPECIALIST_NODE_NAMES = set(SPECIALIST_NODE_NAMES.values())
_SPECIALIST_TOOL_NODE_NAMES = set(SPECIALIST_TOOL_NODE_NAMES.values())

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
    # Per-request Gemini reasoning effort for the main agent model only (the
    # summarizer is always fixed at "medium" — see agent/models/model_2.py).
    # Omit to leave Gemini's own default thinking behavior in place.
    thinking_level: Literal["minimal", "low", "medium", "high"] | None = None


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


def _file_event_from_tool_output(output_text: str) -> dict | None:
    """Parse `export_document`'s JSON result into a "file" event, if well-formed.

    Returns None (falling back to a normal "tool_result" event) if the tool
    actually errored — its output won't be the expected shape in that case.
    """
    try:
        data = json.loads(output_text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or "downloadUrl" not in data or "filename" not in data:
        return None
    return {"type": "file", "filename": data["filename"], "url": data["downloadUrl"]}


# Headers distinctive enough to a *summarization scaffold* (ours, in
# agent/middleware_registry.py, or langchain's own built-in default) that
# seeing one as the very first line of a message is a reliable signal —
# legitimate answers essentially never open with these exact phrases (unlike
# "SUMMARY" or "NEXT STEPS" alone, which are too generic/common in real
# answers to use as the trigger).
_SCAFFOLD_TRIGGER_HEADERS = frozenset({"session intent", "user goal", "resolved ids", "key facts", "artifacts"})

# Both prompt formats define "NEXT STEPS" as their LAST section — look past
# its last occurrence (accepting a markdown "##" prefix or a bare line) for
# where real prose might resume.
_NEXT_STEPS_RE = re.compile(r"(?:\A|\n)[ \t]*#{0,3}[ \t]*next steps[ \t]*\n", re.IGNORECASE)

# The observed leak pattern doesn't insert a paragraph break before the real
# reply — the model runs straight from its last scaffold sentence into the
# real one, so the only seam is a period immediately followed by a
# capitalized word with NO space (e.g. "...return them.To create a new
# team..."). Real prose essentially never does this (a period is always
# followed by a space or newline), which is what makes it a safe signal.
_GLUED_SENTENCE_RE = re.compile(r"\.(?=[A-Z][a-z])")
_PARAGRAPH_BREAK_RE = re.compile(r"\n[ \t]*\n")


def _first_line(text: str) -> str:
    return text.lstrip().split("\n", 1)[0].strip().lstrip("#").strip().lower()


def _strip_leaked_scaffolding(text: str) -> str:
    """Strip a leaked internal-planning preamble off the front of model output.

    `SummarizationMiddleware` (see `agent/middleware_registry.py`) re-injects
    its extracted context as a plain message the model then sees like part of
    the conversation — a fast/small model can respond by literally
    continuing/echoing that structure for a step (sometimes running straight
    into its real answer with no separator at all) instead of treating it as
    silent background context. That's a real, observed failure mode, not a
    hypothetical.

    Only triggers when the message's FIRST line is one of a handful of
    phrases that are distinctive to this scaffold and don't occur in normal
    answers, to keep the false-positive rate on genuine replies near zero.
    """
    if _first_line(text) not in _SCAFFOLD_TRIGGER_HEADERS:
        return text

    next_steps_matches = list(_NEXT_STEPS_RE.finditer(text))
    tail = text[next_steps_matches[-1].end() :] if next_steps_matches else text

    glued = _GLUED_SENTENCE_RE.search(tail)
    if glued:
        return tail[glued.start() + 1 :].strip()

    para_break = _PARAGRAPH_BREAK_RE.search(tail)
    if para_break:
        return tail[para_break.end() :].strip()

    return ""


async def _run_agent_job(
    job_id: str,
    message: str,
    thread_id: str,
    taskflow_token: str,
    thinking_level: str | None = None,
) -> None:
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
        agent = await build_compiled_graph(taskflow_token=taskflow_token, thinking_level=thinking_level)

        async def consume() -> None:
            # "messages" mode streams AI text for EVERY model call anywhere in
            # the graph — not just the active specialist's, and not just the
            # last step. Two distinct things must be kept out of the visible
            # "token" stream:
            #   1. `agent/flow_nodes/summarizer.py`'s OWN model call (it runs
            #      in the "summarize" node) — this hand-built graph has none
            #      of `create_agent`'s internal-call filtering, so without
            #      this check its raw summary text streams in exactly like a
            #      real answer. Filtered by `metadata["langgraph_node"]`,
            #      checked as each chunk arrives — cheapest and most reliable
            #      place to stop it, since it's dropped before ever reaching
            #      the buffer.
            #   2. Real specialist node text from a step that goes on to call a
            #      tool — including an explicit handoff tool call (agent/
            #      handoff_tools.py) — the model "thinking out loud" or
            #      handing off, not the final answer. Can't classify this
            #      until the step finishes, so it's buffered and only
            #      labeled once the matching "updates" chunk arrives:
            #      tool_calls present -> "reasoning" (shown separately,
            #      muted); no tool_calls at all -> the actual final answer,
            #      "token" — a specialist that calls no tool (including no
            #      handoff) is, by construction, always the turn's last word
            #      (see graph_executor.py's `_route_after_summarize`), so
            #      this can be decided immediately, no deferral needed.
            pending_text: list[str] = []

            async for stream_mode, chunk in agent.astream(
                {"messages": [{"role": "user", "content": message}], "taskflow_token": taskflow_token},
                config={"configurable": {"thread_id": thread_id}},
                stream_mode=["messages", "updates"],
            ):
                if stream_mode == "updates":
                    agent_key = next((name for name in _SPECIALIST_NODE_NAMES if name in chunk), None)
                    if agent_key:
                        ai_message = chunk[agent_key]["messages"][0]
                        raw_text = "".join(pending_text)
                        text = _strip_leaked_scaffolding(raw_text)
                        pending_text = []
                        if not ai_message.tool_calls and raw_text and not text:
                            # The final step's ENTIRE output was scaffolding
                            # with nothing real after it — staying silent
                            # would just look like the request hung.
                            text = (
                                "I got sidetracked while working on that — could you ask again?"
                            )
                        event_type = "reasoning" if ai_message.tool_calls else "token"
                        if text:
                            job["events"].append({"type": event_type, "content": text})
                        for call in ai_message.tool_calls:
                            job["events"].append(
                                {"type": "tool_call", "tool": call["name"], "args": call["args"]}
                            )
                    tool_key = next((name for name in _SPECIALIST_TOOL_NODE_NAMES if name in chunk), None)
                    if tool_key:
                        for tool_message in chunk[tool_key]["messages"]:
                            output_text = _extract_text(tool_message.content)
                            file_event = (
                                _file_event_from_tool_output(output_text)
                                if tool_message.name == "export_document"
                                else None
                            )
                            job["events"].append(
                                file_event
                                or {
                                    "type": "tool_result",
                                    "tool": tool_message.name,
                                    "output": output_text,
                                }
                            )
                    if "limit_reached" in chunk:
                        # model_limit.py's per-run step-limit guard tripped.
                        # Its message is a plain, fixed notice — always the
                        # real (and final) answer for this turn.
                        limit_message = chunk["limit_reached"]["messages"][0]
                        job["events"].append({"type": "token", "content": _extract_text(limit_message.content)})
                    # "summarize" node updates (RemoveMessage/HumanMessage
                    # churn from agent/flow_nodes/summarizer.py) are
                    # deliberately not handled here — internal bookkeeping
                    # the user should never see.
                elif stream_mode == "messages":
                    message_chunk, metadata = chunk
                    # Only a real specialist node's own streamed text counts —
                    # see the "summarize" node's leak risk explained above.
                    if metadata.get("langgraph_node") not in _SPECIALIST_NODE_NAMES:
                        continue
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
                        pending_text.append(text)

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
    except asyncio.CancelledError:
        # POST /chat/{job_id}/stop cancelled our own task. `CancelledError`
        # deliberately isn't an `Exception` subclass, so it needs its own
        # branch — the generic handler below never sees it. Record the
        # terminal state, then re-raise: swallowing a CancelledError instead
        # of letting it propagate is exactly the mistake asyncio warns about,
        # since it's how the task actually finishes cancelling.
        job["status"] = "cancelled"
        job["events"].append({"type": "stopped", "message": "Stopped by request. You can resume by typing Continue"})
        raise
    except ModelError as exc:
        # langchain_core's provider-agnostic model-failure hierarchy — covers
        # rate limits (429), server errors (5xx, e.g. Gemini's own "504
        # Deadline expired" when ITS backend is slow/overloaded — not
        # something LLM_TIMEOUT_SECONDS/LLM_MAX_RETRIES in connection/
        # config.py can prevent, only bound how long we keep retrying it),
        # timeouts, and connection failures uniformly. `str(exc)` on the raw
        # provider exception is the ugly nested-JSON blob the SDK gets back
        # — `exc.is_retryable` is enough to give a clean, honest message
        # without repeating that.
        message = (
            "The AI provider had a temporary problem responding to this request "
            "(a rate limit or a brief outage on their side) — please try again."
            if exc.is_retryable
            else f"The AI provider rejected this request ({type(exc).__name__}): {exc}"
        )
        job["events"].append({"type": "error", "message": message})
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
    jobs[job_id] = {"status": "running", "events": [], "created_at": time.monotonic(), "task": None}
    task = asyncio.create_task(
        _run_agent_job(job_id, request.message, request.thread_id, taskflow_token, request.thinking_level)
    )
    jobs[job_id]["task"] = task

    return {"job_id": job_id}


@app.get("/chat/{job_id}")
async def chat_status(job_id: str) -> dict:
    """Poll a chat job's accumulated events and current status."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    return {"status": job["status"], "events": job["events"]}


@app.post("/chat/{job_id}/stop")
async def stop_chat(job_id: str) -> dict:
    """Abort an in-progress chat turn — the "Stop generating" button.

    Best-effort: it prevents any FURTHER model/tool calls, but can't undo a
    side-effecting tool call (e.g. create_task) the model had already
    dispatched to the TaskFlow backend the instant before this was called.
    Everything gathered before the stop stays in the job's events, same as a
    normal finish. Idempotent — stopping an already-finished job just
    reports its current status rather than erroring.
    """
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    if job["status"] == "running":
        job["task"].cancel()
    return {"status": job["status"]}


@app.get("/files/{file_id}")
async def download_file(file_id: str):
    """Serve a document `export_document` generated (see dedicated_tools/).

    One-shot by design: the file is deleted from disk right after this
    response finishes sending (dedicated_tools/store.py's `release_file`, run
    as a background task) — the same `file_id` won't work a second time.
    """
    entry = get_file(file_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown or already-downloaded file_id.")
    return FileResponse(
        path=entry["path"],
        filename=entry["filename"],
        background=BackgroundTask(release_file, file_id),
    )


@app.get("/health")
async def health() -> dict:
    """Health check for Render (and anything else pinging the service).

    Echoes the resolved model config so a stale env var (this process is
    still running on whatever GEMINI_MODEL/GEMINI_SUMMARIZER_MODEL was set
    when it started — see connection/config.py's @lru_cache) is a one-request
    check instead of a LangSmith trace dig.
    """
    return {
        "success": True,
        "message": "Taskflow Agent is UP and RUNNING...",
        "geminiModel": config["GEMINI_MODEL"],
        "geminiSummarizerModel": config["GEMINI_SUMMARIZER_MODEL"],
    }


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
