"""Loads app configuration from environment variables / a .env file.

Plain Python — no pydantic-settings. `load_dotenv()` copies whatever is in
the project's `.env` file into `os.environ`, then we just read each value
back out with `os.environ.get(...)`.
"""

import os

from functools import lru_cache

from dotenv import load_dotenv

@lru_cache(maxsize=1)
def get_config() -> dict:
    """Return the app config as a plain dict.

    `lru_cache` means this function's body only actually runs once (the
    first time it's called) — every call after that just returns the same
    cached dict straight away, instead of re-reading the .env file again.
    """
    load_dotenv()

    return {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
        "GEMINI_MODEL": os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
        "GEMINI_EMBEDDING_MODEL": os.environ.get(
            "GEMINI_EMBEDDING_MODEL", "models/text-embedding-004"
        ),
        "LLM_TEMPERATURE": float(os.environ.get("LLM_TEMPERATURE", "0.2")),
        "LLM_MAX_TOKENS": int(os.environ.get("LLM_MAX_TOKENS", "1024")),
        # The google-genai SDK passes `timeout=None` straight through to its
        # httpx client when unset, meaning NO client-side timeout at all — a
        # slow/stuck Gemini call can then hang for as long as
        # main.py's own 180s asyncio.wait_for allows, silently eating the
        # whole budget instead of failing fast. Bounding it here well below
        # that 180s lets a stuck call retry and still finish inside the job.
        "LLM_TIMEOUT_SECONDS": int(os.environ.get("LLM_TIMEOUT_SECONDS", "45")),
        "LLM_MAX_RETRIES": int(os.environ.get("LLM_MAX_RETRIES", "2")),
        "MODEL_CALL_LIMIT_PER_THREAD": int(
            os.environ.get("MODEL_CALL_LIMIT_PER_THREAD", "20")
        ),
        "MODEL_CALL_LIMIT_PER_RUN": int(os.environ.get("MODEL_CALL_LIMIT_PER_RUN", "10")),
        "GEMINI_SUMMARIZER_MODEL": os.environ.get("GEMINI_SUMMARIZER_MODEL", "gemini-2.0-flash"),
        "TASKFLOW_API_BASE_URL": os.environ.get("TASKFLOW_API_BASE_URL", "http://localhost:5000"),
        "TASKFLOW_API_TOKEN": os.environ.get("TASKFLOW_API_TOKEN", ""),
        # "stdio": the agent spawns taskflow-mcp-server itself as a subprocess.
        # "streamable_http": the agent connects to an already-running server over HTTP.
        "MCP_TRANSPORT": os.environ.get("MCP_TRANSPORT", "stdio"),
        "MCP_SERVER_HOST": os.environ.get("MCP_SERVER_HOST", "127.0.0.1"),
        "MCP_SERVER_PORT": int(os.environ.get("MCP_SERVER_PORT", "8765")),
        "MCP_SERVER_URL": os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8765/mcp"),
        # LangSmith tracing itself is picked up automatically by LangChain from
        # these same env vars (load_dotenv() above already put them in
        # os.environ) — nothing else needs to read this dict for tracing to
        # work. Kept here too just so every setting is visible in one place.
        "LANGSMITH_TRACING": os.environ.get("LANGSMITH_TRACING", "false"),
        "LANGSMITH_API_KEY": os.environ.get("LANGSMITH_API_KEY", ""),
        "LANGSMITH_PROJECT": os.environ.get("LANGSMITH_PROJECT", "taskflow-agent"),
        "LANGSMITH_ENDPOINT": os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
        # RAG vectorstore: Supabase Postgres + pgvector (not a local folder —
        # Render's disk is wiped on every redeploy, so the vector data has to
        # live in a separate managed database instead).
        "SUPABASE_DB_URL": os.environ.get("SUPABASE_DB_URL", ""),
        "PGVECTOR_COLLECTION_NAME": os.environ.get(
            "PGVECTOR_COLLECTION_NAME", "taskflow_knowledge_base"
        ),
        "CHUNK_SIZE": int(os.environ.get("CHUNK_SIZE", "1000")),
        "CHUNK_OVERLAP": int(os.environ.get("CHUNK_OVERLAP", "150")),
        "KNOWLEDGE_BASE_DIR": os.environ.get("KNOWLEDGE_BASE_DIR", "data/knowledge_base"),
    }


# Every other module imports this and uses it directly, e.g. config["GEMINI_MODEL"].
config = get_config()
