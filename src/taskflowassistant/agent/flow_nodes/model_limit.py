from taskflowassistant.connection.config import config
from langchain_core.messages import AIMessage
from langgraph.prebuilt import tools_condition
from taskflowassistant.agent.schema.state import TaskFlowState


async def limit_reached_node(state: TaskFlowState) -> dict:
    return {
        "messages": [
            AIMessage(
                content="I've hit the maximum number of steps I can take on this request. "
                "Here's what I found so far — let me know if you'd like me to continue."
            )
        ]
    }

def route_after_agent(state: TaskFlowState) -> str:
    # Check what the agent actually wants to do FIRST. If it already produced
    # a clean final answer (no more tool calls), let it end naturally even if
    # the call count happens to be at/over the limit on this exact step —
    # otherwise a good answer gets a bogus "I've hit the maximum steps"
    # message appended after it. The limit should only ever intervene when
    # the agent wants to keep going but isn't allowed to anymore.
    decision = tools_condition(state)
    if decision == "tools" and state.get("llm_calls", 0) >= config["MODEL_CALL_LIMIT_PER_RUN"]:
        return "limit_reached"
    return decision