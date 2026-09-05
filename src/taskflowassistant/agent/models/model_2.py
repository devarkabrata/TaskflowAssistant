from taskflowassistant.agent.models.model_1 import build_model
from taskflowassistant.connection.config import config


def build_summarizer_model(model_provider: str | None = None, model_name: str | None = None):
    """Construct the model used for context compaction (flow_nodes/summarizer.py).

    Fixed at "medium" thinking, always — this is an internal bookkeeping
    step, not something a caller should be tuning turn by turn. Its
    provider/model ARE caller-controlled though (main.py's ChatRequest.
    summarizer_model_provider/summarizer_model_name) — separately from the
    supervisor/specialists' own model_provider/model_name, so the summarizer
    can keep using its own (usually cheaper) default model
    (config["GEMINI_SUMMARIZER_MODEL"]) instead of being forced to match
    whatever the main model is. Omit both to use that default.
    """
    return build_model(
        thinking_level="medium",
        model_provider=model_provider or "google_genai",
        model_name=model_name or config["GEMINI_SUMMARIZER_MODEL"],
    )
