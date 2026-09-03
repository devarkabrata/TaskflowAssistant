from langchain.chat_models import init_chat_model
from taskflowassistant.connection.config import config


def build_model():
    """Construct the Gemini chat model used by the agent."""
    return init_chat_model(
        model=config["GEMINI_MODEL"],
        model_provider="google_genai",
        api_key=config["GEMINI_API_KEY"],
        temperature=config["LLM_TEMPERATURE"],
        max_tokens=config["LLM_MAX_TOKENS"],
    )