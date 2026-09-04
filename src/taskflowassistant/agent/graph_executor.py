from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, START, END

from taskflowassistant.agent.flow_nodes.hydrate_user import hydrate_user_node
from taskflowassistant.agent.flow_nodes.specialist_agent import make_specialist_node
from taskflowassistant.agent.flow_nodes.supervisor import supervisor_node
from taskflowassistant.agent.flow_nodes.model_limit import limit_reached_node, route_after_agent
from taskflowassistant.agent.flow_nodes.summarizer import maybe_summarize_node
from taskflowassistant.agent.handoff_tools import HANDOFF_TOOL_PREFIX

from taskflowassistant.agent.schema.state import TaskFlowState
from taskflowassistant.agent.memory import checkpointer
from taskflowassistant.agent.tool_groups import SPECIALIST_NAMES
from taskflowassistant.agent.tools_registry import get_grouped_tools

# e.g. {"task": "task_agent", "team": "team_agent", ..., "knowledge": "knowledge_agent"}
SPECIALIST_NODE_NAMES: dict[str, str] = {name: f"{name}_agent" for name in SPECIALIST_NAMES}
# e.g. {"task": "task_tools", ...} — one PRIVATE ToolNode per specialist, not
# one shared across all of them: each only ever needs to execute a call for
# a tool it was itself bound (see specialist_agent.py), and keeping the
# node private means a specialist's own loop is a fixed, static pair of
# edges instead of a lookup.
SPECIALIST_TOOL_NODE_NAMES: dict[str, str] = {name: f"{name}_tools" for name in SPECIALIST_NAMES}


def _route_after_tools(domain: str):
    """After this domain's ToolNode executes, was any of the tool call(s)
    that just ran an explicit handoff (agent/handoff_tools.py), or a normal
    domain/export tool?

    A handoff means this specialist is done with its part and control needs
    to leave this domain — go through "summarize" (see `_route_after_summarize`
    below, which reads the handoff ToolMessage's name to pick the target).
    Anything else is this specialist's own tool result — loop straight back
    to it directly, unchanged from before.
    """
    own_agent_node = SPECIALIST_NODE_NAMES[domain]

    def router(state: TaskFlowState) -> str:
        last_ai_message = next(m for m in reversed(state["messages"]) if isinstance(m, AIMessage))
        if any(call["name"].startswith(HANDOFF_TOOL_PREFIX) for call in last_ai_message.tool_calls):
            return "summarize"
        return own_agent_node

    return router


def _route_after_summarize(state: TaskFlowState) -> str:
    """`summarize` is reached from three different places, and its own
    outgoing edge is read directly off the last message rather than a
    separately-maintained state field — no extra bookkeeping to keep in sync:
      - hydrate_user (turn start): last message is the user's fresh
        HumanMessage -> go to the supervisor for the turn's one routing call.
      - a specialist's own "no more tool calls" branch (route_after_agent's
        END case): last message is that specialist's own plain final answer
        -> the turn is over.
      - `_route_after_tools` above, after a handoff tool executed: last
        message is a ToolMessage named "handoff_to_<domain>" -> go straight
        to that domain's specialist. Deterministic string parsing, no model
        call — see agent/handoff_tools.py's module docstring for why.
    """
    last_message = state["messages"][-1]
    if isinstance(last_message, HumanMessage):
        return "supervisor"
    if isinstance(last_message, ToolMessage) and (last_message.name or "").startswith(HANDOFF_TOOL_PREFIX):
        target_domain = last_message.name[len(HANDOFF_TOOL_PREFIX):]
        return SPECIALIST_NODE_NAMES[target_domain]
    return END


async def build_graph(taskflow_token: str | None = None, thinking_level: str | None = None):

    # One MCP subprocess spawn for this whole job — see tools_registry.py's
    # docstring for why every domain's tools are derived from one load.
    grouped_tools = await get_grouped_tools(taskflow_token)

    graph = StateGraph(TaskFlowState)

    # ==== NODES ====
    graph.add_node("hydrate_user", hydrate_user_node)
    graph.add_node("summarize", maybe_summarize_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("limit_reached", limit_reached_node)

    for domain in SPECIALIST_NAMES:
        tools = grouped_tools[domain]
        graph.add_node(SPECIALIST_NODE_NAMES[domain], make_specialist_node(domain, tools, thinking_level))
        graph.add_node(SPECIALIST_TOOL_NODE_NAMES[domain], ToolNode(tools))

    # ==== EDGES ====
    # hydrate_user runs once per THREAD (a no-op on every turn after the
    # first — see flow_nodes/hydrate_user.py) so the caller's own profile is
    # cached before the supervisor's one routing decision.
    graph.add_edge(START, "hydrate_user")
    graph.add_edge("hydrate_user", "summarize")

    # "summarize" now has three possible destinations depending on how it
    # was reached — see `_route_after_summarize` above.
    graph.add_conditional_edges(
        "summarize",
        _route_after_summarize,
        {
            "supervisor": "supervisor",
            END: END,
            **{node_name: node_name for node_name in SPECIALIST_NODE_NAMES.values()},
        },
    )

    # The supervisor runs exactly once per turn (see flow_nodes/supervisor.py)
    # and always picks one of the five domains — no "done"/limit sentinel
    # needed here anymore, that's handled structurally by the edges below.
    graph.add_conditional_edges(
        "supervisor",
        lambda state: state["active_specialist"],
        SPECIALIST_NODE_NAMES,
    )

    for domain in SPECIALIST_NAMES:
        agent_node_name = SPECIALIST_NODE_NAMES[domain]
        tool_node_name = SPECIALIST_TOOL_NODE_NAMES[domain]

        # Did this specialist ask for a tool (domain, export, or handoff —
        # tools_condition doesn't distinguish), and is it still under the
        # per-run call limit? A "no more tools" answer with nothing left to
        # hand off means this specialist's own final answer IS the turn's
        # answer — that's confirmed by `_route_after_summarize` next, not
        # assumed here.
        graph.add_conditional_edges(
            agent_node_name,
            route_after_agent,
            {"tools": tool_node_name, "limit_reached": "limit_reached", END: "summarize"},
        )
        # A normal domain/export tool call loops straight back to this same
        # specialist (no summarize in between); a handoff tool call instead
        # goes to "summarize" — see `_route_after_tools` above.
        graph.add_conditional_edges(
            tool_node_name,
            _route_after_tools(domain),
            {"summarize": "summarize", agent_node_name: agent_node_name},
        )

    graph.add_edge("limit_reached", END)

    return graph


async def build_compiled_graph(taskflow_token: str | None = None, thinking_level: str | None = None):
    graph = await build_graph(taskflow_token, thinking_level)
    return graph.compile(checkpointer=checkpointer)
