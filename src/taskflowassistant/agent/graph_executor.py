from collections import OrderedDict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, START, END

from taskflowassistant.agent.flow_nodes.hydrate_user import hydrate_user_node
from taskflowassistant.agent.flow_nodes.specialist_agent import make_specialist_node
from taskflowassistant.agent.flow_nodes.supervisor import make_supervisor_node
from taskflowassistant.agent.flow_nodes.model_limit import limit_reached_node, route_after_agent
from taskflowassistant.agent.flow_nodes.summarizer import make_summarize_node
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


async def build_graph(
    taskflow_token: str | None = None,
    thinking_level: str | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    summarizer_model_provider: str | None = None,
    summarizer_model_name: str | None = None,
):

    # One MCP subprocess spawn for this whole job — see tools_registry.py's
    # docstring for why every domain's tools are derived from one load.
    grouped_tools = await get_grouped_tools(taskflow_token)

    graph = StateGraph(TaskFlowState)

    # ==== NODES ====
    graph.add_node("hydrate_user", hydrate_user_node)
    # summarizer_model_provider/summarizer_model_name are separate from
    # model_provider/model_name below — see agent/flow_nodes/summarizer.py's
    # make_summarize_node docstring for why. Only the RAG embedding model
    # stays fixed to Gemini regardless of any of this.
    graph.add_node("summarize", make_summarize_node(summarizer_model_provider, summarizer_model_name))
    # model_provider/model_name apply to the supervisor and every specialist
    # alike — the caller's one choice for the whole turn (agent/models/
    # model_1.py).
    graph.add_node("supervisor", make_supervisor_node(model_provider, model_name))
    graph.add_node("limit_reached", limit_reached_node)

    for domain in SPECIALIST_NAMES:
        tools = grouped_tools[domain]
        specialist_node = make_specialist_node(domain, tools, thinking_level, model_provider, model_name)
        graph.add_node(SPECIALIST_NODE_NAMES[domain], specialist_node)
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


# Caches the fully COMPILED graph itself, keyed on everything that could
# actually change its shape or the models/tools wired into it. With
# mcp/client.py's MCP session cache, rag/vectorstore.py's vectorstore cache,
# and agent/models/model_1.py's model-client cache all warm, rebuilding the
# graph from scratch costs ~70ms (measured) — no I/O left in it, just
# StateGraph/`.compile()` bookkeeping and `bind_tools()`/
# `with_structured_output()` wrapping. That's cheap enough that a single
# shared graph across every caller isn't worth the risk it would take to get
# there (LangGraph's `ToolNode` binds a fixed tool list at construction time,
# and each caller's MCP tools are distinct objects scoped to their own token
# — sharing one graph across callers would mean hand-reimplementing
# `ToolNode`'s dispatch to pick the right caller's tools per invocation,
# real correctness surface for a further ~70ms). Caching per-key instead
# reuses the exact same LangGraph pattern already used everywhere else here
# (one compiled graph, invoked many times with different thread_ids) while
# keeping each caller's tools/models fully isolated.
_MAX_CACHED_GRAPHS = 128
_compiled_graph_cache: OrderedDict[tuple, object] = OrderedDict()


async def build_compiled_graph(
    taskflow_token: str | None = None,
    thinking_level: str | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    summarizer_model_provider: str | None = None,
    summarizer_model_name: str | None = None,
):
    """Return the compiled graph for this exact config, building it once and
    reusing it for every later call with the same arguments.

    Every argument is part of the cache key — a message reusing all of them
    (the common case: same caller, same model choices as their last message)
    gets back the same compiled graph instance instead of a fresh rebuild;
    changing any one of them (a token refresh, switching model_provider, ...)
    naturally misses the cache and builds a new entry, same as before. Bounded
    to `_MAX_CACHED_GRAPHS` least-recently-used entries so a long-running
    deployment with many distinct callers/configs doesn't grow this forever.
    """
    key = (
        taskflow_token,
        thinking_level,
        model_provider,
        model_name,
        summarizer_model_provider,
        summarizer_model_name,
    )
    cached = _compiled_graph_cache.get(key)
    if cached is not None:
        _compiled_graph_cache.move_to_end(key)
        return cached

    graph = await build_graph(
        taskflow_token,
        thinking_level,
        model_provider,
        model_name,
        summarizer_model_provider,
        summarizer_model_name,
    )
    compiled = graph.compile(checkpointer=checkpointer)

    _compiled_graph_cache[key] = compiled
    if len(_compiled_graph_cache) > _MAX_CACHED_GRAPHS:
        _compiled_graph_cache.popitem(last=False)
    return compiled
