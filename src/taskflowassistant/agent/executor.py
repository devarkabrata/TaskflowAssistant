"""Builds the TaskFlow agent using LangChain's init_chat_model + create_agent.

Tools come from `agent/tools_registry.py` (MCP + RAG tools, assembled
there) — this file just wires model + system prompt + tools + memory +
middleware together and doesn't need to know where the tools came from.
"""

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from taskflowassistant.agent.memory import checkpointer
from taskflowassistant.agent.middleware_registry import middlewares
from taskflowassistant.agent.tools_registry import get_tools
from taskflowassistant.connection.config import config
from taskflowassistant.prompts.system_prompt import get_system_prompt


def build_model():
    """Construct the Gemini chat model used by the agent."""
    return init_chat_model(
        model=config["GEMINI_MODEL"],
        model_provider="google_genai",
        api_key=config["GEMINI_API_KEY"],
        temperature=config["LLM_TEMPERATURE"],
        max_tokens=config["LLM_MAX_TOKENS"],
    )


async def build_agent(taskflow_token: str | None = None):
    """Build the TaskFlow agent: model + system prompt + tools + memory + middleware.

    Async because tool loading is async (see agent/tools_registry.py) — call
    this with `await build_agent()` from inside an event loop (e.g. an
    asyncio.run(), or a FastAPI request handler).

    `taskflow_token`, if given, is forwarded to the MCP tools so they act on
    behalf of the actual caller for this one agent instance, instead of the
    static TASKFLOW_API_TOKEN in .env. Since this spawns a fresh MCP
    subprocess per call, build one agent per request rather than reusing a
    single instance across requests.
    """
    model = build_model()
    system_prompt = get_system_prompt()
    tools = await get_tools(taskflow_token)

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middlewares,
        checkpointer=checkpointer,
    )
