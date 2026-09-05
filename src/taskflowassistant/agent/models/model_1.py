"""Builds the chat model used by the agent's supervisor and specialists.

Provider/model are parameters, not hardcoded to Gemini, so a future provider
can be added by (1) installing its langchain-<provider> package, (2) adding
its API key lookup to `_PROVIDER_API_KEYS` below, and (3) adding it to
`SUPPORTED_MODEL_PROVIDERS` — nothing else needs to change, since main.py's
`ChatRequest.model_provider`/`model_name` already thread through end-to-end
to here (see flow_nodes/supervisor.py and flow_nodes/specialist_agent.py).
"google_genai" (Gemini) and "groq" are wired up. The RAG embedding model
(connection/config.py's GEMINI_EMBEDDING_MODEL) is unaffected by any of
this — it stays on Gemini regardless of what a request picks for chat, and
so does the summarizer (agent/models/model_2.py).

`build_model` is `@lru_cache`d: every graph build (currently once per chat
message — see agent/graph_executor.py) calls this once for the supervisor
and once per specialist, almost always with the same
(thinking_level, model_provider, model_name) triple as the previous message
in the same conversation. Caching means that triple's `init_chat_model(...)`
client is only actually constructed once and reused after that, instead of
rebuilt on every message. `maxsize=64` bounds the cache rather than leaving
it unbounded, since `model_name` is caller-supplied free text — comfortably
above the realistic number of distinct configs any deployment would
actually use, so real traffic never evicts a live entry.
"""

from functools import lru_cache

from langchain.chat_models import init_chat_model
from taskflowassistant.connection.config import config

# Every provider a caller is allowed to request via POST /chat's
# model_provider field (see main.py's ChatRequest) — kept as its own tuple
# (not just "whatever _PROVIDER_API_KEYS happens to have") so main.py can
# reject an unsupported provider before ever starting a background job,
# instead of failing deep inside the graph build.
SUPPORTED_MODEL_PROVIDERS = ("google_genai", "groq")

# How to fetch each supported provider's API key — a callable (not the key
# itself) so this stays cheap to declare even for a provider with no key
# configured, and reads `config` fresh each time rather than at import time.
_PROVIDER_API_KEYS = {
    "google_genai": lambda: config["GEMINI_API_KEY"],
    "groq": lambda: config["GROQ_API_KEY"],
}

# Gemini's own reasoning-effort mechanism (thinking_config) is Gemini-
# specific — only ever sent when the request is actually going to Gemini.
_PROVIDERS_SUPPORTING_THINKING_CONFIG = {"google_genai"}


@lru_cache(maxsize=64)
def build_model(
    thinking_level: str | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
):
    """Construct the chat model used by the agent's supervisor/specialists.

    `model_provider`/`model_name`, if given, come from the caller's own
    POST /chat payload (main.py's ChatRequest) — which provider/model a
    given turn should use is a caller/UI choice, not a deployment-wide one,
    same reasoning as `thinking_level`. Omit both to use the deployment's
    default (Gemini, `config["GEMINI_MODEL"]`).

    `thinking_level` ("minimal" | "low" | "medium" | "high") only has an
    effect on providers in `_PROVIDERS_SUPPORTING_THINKING_CONFIG` — it's a
    silent no-op on anything else, since other providers don't share
    Gemini's reasoning-effort mechanism.
    """
    provider = model_provider or "google_genai"
    model = model_name or config["GEMINI_MODEL"]

    if provider not in _PROVIDER_API_KEYS:
        raise ValueError(f"Unknown model_provider '{provider}' — not in SUPPORTED_MODEL_PROVIDERS.")

    kwargs = {}
    if thinking_level and provider in _PROVIDERS_SUPPORTING_THINKING_CONFIG:
        kwargs["thinking_config"] = {"thinking_level": thinking_level.upper()}

    return init_chat_model(
        model=model,
        model_provider=provider,
        api_key=_PROVIDER_API_KEYS[provider](),
        temperature=config["LLM_TEMPERATURE"],
        max_tokens=config["LLM_MAX_TOKENS"],
        timeout=config["LLM_TIMEOUT_SECONDS"],
        max_retries=config["LLM_MAX_RETRIES"],
        **kwargs,
    )
