from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, START, END

from taskflowassistant.agent.flow_nodes.hydrate_user import hydrate_user_node
from taskflowassistant.agent.flow_nodes.main_agent import make_agent_node
from taskflowassistant.agent.flow_nodes.model_limit import limit_reached_node, route_after_agent
from taskflowassistant.agent.flow_nodes.summarizer import maybe_summarize_node

from taskflowassistant.agent.schema.state import TaskFlowState
from taskflowassistant.agent.memory import checkpointer

async def build_graph(taskflow_token: str | None = None, thinking_level: str | None = None):

    # Extract Nodes
    agent_node, tools = await make_agent_node(taskflow_token, thinking_level)
    tool_node = ToolNode(tools)

    graph = StateGraph(TaskFlowState)

    # ==== NODES ====
    graph.add_node("hydrate_user", hydrate_user_node)
    graph.add_node("limit_reached", limit_reached_node)
    graph.add_node("summarize", maybe_summarize_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)

    # ==== EDGES ====
    # hydrate_user runs once per THREAD (a no-op on every turn after the
    # first — see flow_nodes/hydrate_user.py) so the caller's own profile is
    # cached before the agent's first real turn.
    graph.add_edge(START, "hydrate_user")
    graph.add_edge("hydrate_user", "summarize")
    graph.add_edge("tools", "summarize")
    graph.add_edge("summarize", "agent")
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {"tools": "tools", "limit_reached": "limit_reached", END: END},
    )
    graph.add_edge("limit_reached", END)

    return graph


async def build_compiled_graph(taskflow_token: str | None = None, thinking_level: str | None = None):
    graph = await build_graph(taskflow_token, thinking_level)
    return graph.compile(checkpointer=checkpointer)