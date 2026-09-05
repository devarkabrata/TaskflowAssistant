"""Shared helper for the multi-agent graph's separate model instances
(flow_nodes/supervisor.py's router model, and each domain's own model in
flow_nodes/specialist_agent.py).

Gemini 3's thinking models attach a cryptographic "thought signature" to
response content (Gemini's list-content format carries an `extras.signature`
field per block) so a multi-turn conversation with THAT SAME model instance
can maintain reasoning continuity across calls. This graph's supervisor and
every specialist are separate `ChatGoogleGenerativeAI` instances that all
read and write the same `state["messages"]` list — passing a signature
produced by one of them into any of the others reproduces, verified directly
against the real API while debugging this:
  - a hard "400 INVALID_ARGUMENT: Corrupted thought signature" error, or
  - worse, no error at all: a silent EMPTY response from the receiving model,
    which is what actually happened in production (the supervisor kept
    re-routing to the same specialist because its structured-output call
    itself was degraded by the corrupted context it was reading, not because
    of any prompt/logic bug in the routing decision).
"""

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

_EMPTY_TOOL_RESULT_PLACEHOLDER = "(no data returned)"

# Some Gemini models (e.g. gemini-3.5-flash-lite, gemini-3.6-flash — see
# langchain_google_genai.chat_models._FIXED_SAMPLING_AND_NO_PREFILL_MODELS)
# reject any request whose final turn is model-authored ("does not support
# model prefilling"). This graph's supervisor is re-consulted right after a
# specialist answers, and a second specialist can be invoked right after a
# first one answers — both cases end `state["messages"]` on an AIMessage
# with no new user turn in between, which is exactly what those models
# reject. Confirmed directly against `ChatGoogleGenerativeAI._prepare_request`
# while debugging this. This placeholder is appended ONLY to the local list
# built for one `.ainvoke()` call (see supervisor.py/specialist_agent.py) —
# it is never returned from a node and never enters the persisted
# `state["messages"]`.
_CONTINUATION_PLACEHOLDER = HumanMessage(
    content=(
        "[No new message from the user — this is an internal continuation "
        "step. Decide/respond based on the conversation so far.]"
    )
)


def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def strip_thought_signatures(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Return a copy of `messages` with every AIMessage's content collapsed
    to plain text, dropping any thought-signature metadata.

    Safe to apply unconditionally, including inside one specialist's own
    tool-calling loop (not just at the supervisor/cross-specialist
    boundary) — the only thing lost is Gemini's own continuity optimization
    within that one loop, which this app was never relying on, in exchange
    for never risking the corruption/empty-response failure above anywhere
    messages cross between the graph's several separate model instances.
    """
    sanitized = []
    for message in messages:
        if isinstance(message, AIMessage) and isinstance(message.content, list):
            sanitized.append(message.model_copy(update={"content": _content_to_text(message.content)}))
        else:
            sanitized.append(message)
    return sanitized


def ensure_valid_trailing_turn(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Append a synthetic user turn if `messages` currently ends on an
    AIMessage — see the module docstring above for why some Gemini models
    reject that shape outright. A no-op for every other model too, so it's
    safe to apply unconditionally regardless of which model is configured.
    """
    if messages and isinstance(messages[-1], AIMessage):
        return [*messages, _CONTINUATION_PLACEHOLDER]
    return messages


def ensure_non_empty_tool_content(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Replace any ToolMessage's genuinely empty content (`""` or `[]`) with
    a placeholder before it reaches any model.

    Reproduced directly: a tool call that legitimately returns "nothing" —
    the RAG retriever finding zero matches, an MCP tool like `list_teams`
    returning an empty list — can end up as a ToolMessage with EMPTY
    content once it passes through LangChain's/MCP's own serialization.
    Gemini tolerates an empty tool-result content; Groq's stricter
    OpenAI-compatible schema rejects the whole request outright ("for
    'role:tool' ... minimum number of items is 1"). Fixed at the source for
    the RAG tool (rag/retriever.py), but MCP tools' own empty-result
    serialization isn't ours to control — this is the general, permanent
    backstop so no tool, present or future, can trigger this again.
    """
    sanitized = []
    for message in messages:
        if isinstance(message, ToolMessage) and not message.content:
            sanitized.append(message.model_copy(update={"content": _EMPTY_TOOL_RESULT_PLACEHOLDER}))
        else:
            sanitized.append(message)
    return sanitized


def estimate_token_count(messages: list[AnyMessage]) -> int:
    """Cheap, provider-agnostic token estimate (~4 characters per token, the
    same rule of thumb OpenAI's own docs use) — good enough to decide
    whether flow_nodes/summarizer.py should trim the conversation, not
    meant to be exact.

    Deliberately does NOT call `BaseChatModel.get_num_tokens_from_messages()`
    on whichever model is configured: Gemini has its own token-counting API,
    but a provider with no native one (confirmed live for ChatGroq) falls
    back to langchain_core's default implementation, which needs the
    `transformers` package installed — a real crash, reproduced directly,
    once the summarizer's own provider became caller-selectable (see
    summarizer_model_provider/summarizer_model_name on ChatRequest) instead
    of always being Gemini. This sidesteps that fallback entirely, for any
    provider, present or future.
    """
    return sum(len(_content_to_text(m.content)) for m in messages) // 4
