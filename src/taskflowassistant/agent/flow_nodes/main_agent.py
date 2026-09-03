# taskflowassistant/agent/graph.py
from langchain_core.messages import SystemMessage
from taskflowassistant.agent.tools_registry import get_tools
from taskflowassistant.agent.models.model_1 import build_model
from taskflowassistant.prompts.system_prompt import get_system_prompt
from taskflowassistant.agent.schema.state import TaskFlowState

async def make_agent_node(taskflow_token: str | None):
    tools = await get_tools(taskflow_token)
    model_with_tool = build_model().bind_tools(tools)
    system_prompt = get_system_prompt()

    async def agent_node(state: TaskFlowState) -> dict:
        messages = [SystemMessage(content=system_prompt), *state["messages"]]
        response = await model_with_tool.ainvoke(messages)
        # `llm_calls` is `UntrackedValue` (last-value-wins, not summed) — we
        # must add 1 to the current count ourselves, not just report "1".
        return {"messages": [response], "llm_calls": state.get("llm_calls", 0) + 1}

    return agent_node, tools