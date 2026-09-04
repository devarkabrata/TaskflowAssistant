from langchain.chat_models import init_chat_model
from taskflowassistant.connection.config import config


def build_model(thinking_level: str | None = None):
    """Construct the Gemini chat model used by the agent.

    `thinking_level` ("minimal" | "low" | "medium" | "high") is the one
    per-request knob on this model — it comes from the caller's own
    POST /chat payload (see main.py's ChatRequest.thinking_level), not a
    fixed .env value, since how hard a given turn should think is a
    caller/UI choice, not a deployment-wide one. Omit it to leave Gemini's
    own default thinking behavior in place.
    """
    kwargs = {}
    if thinking_level:
        kwargs["thinking_config"] = {"thinking_level": thinking_level.upper()}

    return init_chat_model(
        model=config["GEMINI_MODEL"],
        model_provider="google_genai",
        api_key=config["GEMINI_API_KEY"],
        temperature=config["LLM_TEMPERATURE"],
        max_tokens=config["LLM_MAX_TOKENS"],
        timeout=config["LLM_TIMEOUT_SECONDS"],
        max_retries=config["LLM_MAX_RETRIES"],
        **kwargs,
    )