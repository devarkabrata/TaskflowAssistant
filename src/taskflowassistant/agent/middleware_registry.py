"""Build the agent's middleware stack.

    - SummarizationMiddleware: once the conversation gets long, older
      messages get replaced with an LLM-generated summary, so the agent
      doesn't keep re-sending (and re-paying for) the full history forever.
    - ModelCallLimitMiddleware: hard caps how many times the agent is
      allowed to call the LLM, so a runaway tool-calling loop can't rack up
      unbounded API cost. `exit_behavior="end"` means it stops cleanly
      instead of raising an error once a limit is hit.
"""

from langchain.agents.middleware import ModelCallLimitMiddleware, SummarizationMiddleware
from langchain.chat_models import init_chat_model

from taskflowassistant.connection.config import config

# Built explicitly (model_provider="google_genai") rather than passing a bare
# model-name string to SummarizationMiddleware — otherwise init_chat_model's
# provider auto-detection picks Vertex AI for "gemini-*" names, not the
# Gemini Developer API this project actually uses.
summarizer_model = init_chat_model(
    model=config["GEMINI_SUMMARIZER_MODEL"],
    model_provider="google_genai",
    api_key=config["GEMINI_API_KEY"],
)

middlewares: list = [
    SummarizationMiddleware(
        model=summarizer_model,
        trigger=("tokens", 5000),
        keep=("messages", 10),
    ),
    ModelCallLimitMiddleware(
        thread_limit=config["MODEL_CALL_LIMIT_PER_THREAD"],
        run_limit=config["MODEL_CALL_LIMIT_PER_RUN"],
        exit_behavior="end",
    ),
]
