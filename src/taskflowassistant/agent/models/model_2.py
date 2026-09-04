from langchain.chat_models import init_chat_model
from taskflowassistant.connection.config import config

def build_summarizer_model():
    """Construct the Gemini model used for context compaction (flow_nodes/summarizer.py).

    Fixed at "medium" thinking — unlike the main model, this isn't exposed
    per-request: summarization is an internal bookkeeping step, not
    something a caller should be tuning turn by turn.
    """
    summarizer_model = init_chat_model(
        model=config["GEMINI_SUMMARIZER_MODEL"],
        model_provider="google_genai",
        api_key=config["GEMINI_API_KEY"],
        thinking_config={"thinking_level": "MEDIUM"},
    )
    return summarizer_model