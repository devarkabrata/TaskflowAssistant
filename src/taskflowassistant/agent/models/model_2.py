from langchain.chat_models import init_chat_model
from taskflowassistant.connection.config import config

def build_summarizer_model():
    summarizer_model = init_chat_model(
        model=config["GEMINI_SUMMARIZER_MODEL"],
        model_provider="google_genai",
        api_key=config["GEMINI_API_KEY"],
    )
    return summarizer_model