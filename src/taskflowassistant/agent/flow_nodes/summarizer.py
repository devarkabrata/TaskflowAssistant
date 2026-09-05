from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, RemoveMessage, ToolMessage
from langchain_core.messages.utils import get_buffer_string
from taskflowassistant.agent.message_utils import estimate_token_count
from taskflowassistant.agent.schema.state import TaskFlowState
from taskflowassistant.agent.models.model_2 import build_summarizer_model

KEEP_LAST = 12
TOKEN_TRIGGER = 8000

# SummarizationMiddleware's own summary-generation call is already kept out of
# the user-visible token stream (it tags that call and `InternalCallTransformer`
# drops it — see langchain.agents.middleware.internal_call_transformer). What
# is NOT filtered is the *next* real model call, which sees the summary
# re-injected as a plain HumanMessage. langchain's built-in `summary_prompt`
# is written for a coding agent (its ARTIFACTS section talks about "files,
# paths, modifications") and doesn't say the summary is private — against a
# fast/small model like gemini-2.0-flash, that combination reliably produces
# a visible bug: the next reply echoes the summary's own section headings
# (e.g. "## ARTIFACTS\nNone\n## NEXT STEPS") before it actually gets to
# answering the user. This TaskFlow-specific prompt fixes both: it swaps the
# coding-agent sections for TaskFlow-relevant ones, and explicitly tells the
# model the extracted context is private and must never be echoed back.
#
# The `<messages>` marker (own line) and `{messages}` placeholder are a
# public contract of the summarization prompt format — keep both verbatim.
_TASKFLOW_SUMMARY_PROMPT = """<role>
Context Extraction Assistant for the TaskFlow Assistant agent
</role>

<primary_objective>
Your sole objective in this task is to extract the highest quality/most relevant context from the conversation history below, so the TaskFlow Assistant can keep helping the user with their tasks, teams, and workspace without losing track of what it has already done.
</primary_objective>

<objective_information>
You're nearing the total number of input tokens you can accept, so you must extract the highest quality/most relevant pieces of information from your conversation history.
This context will then overwrite the conversation history presented below. Because of this, ensure the context you extract is only the most important information needed to keep working toward the user's goal.
</objective_information>

<instructions>
The conversation history below will be replaced with the context you extract in this step. What you produce is PRIVATE working memory for you (the agent) only — it is never shown to the user. When you next reply to the user, never quote it, never repeat its section headings, and never narrate that you are "following next steps" from it. Just use it silently, then respond to the user directly and naturally, as if continuing the conversation.

You want to ensure that you don't repeat any actions you've already completed (tool calls already made, ids already resolved), so focus on the information most important to your overall goal.

Structure your summary using the following sections. Each section acts as a checklist - populate it with relevant information or explicitly state "None" if there is nothing to report:

## USER GOAL

What is the user's current request or overall goal in TaskFlow (e.g. "find how many pending tasks Team X has", "create a task for the Unify V6 team")? Be concise but complete.

## RESOLVED IDS

Any team, user, task, status, or role names already resolved to ids in this conversation (e.g. "Unify V6 Team" -> teamId d5e64f12-...), so they never need to be looked up again.

## KEY FACTS

Important data already fetched from TaskFlow (task counts, board columns, member lists, permissions, etc.) that is still needed to answer the user.

## NEXT STEPS

The specific tool calls or actions still needed to actually answer the user's request.

</instructions>

The user will message you with the full message history from which you'll extract context to create a replacement. Carefully read through it all and think deeply about what information is most important to your overall goal and should be saved:

With all of this in mind, please carefully read over the entire conversation history, and extract the most important and relevant context to replace it so that you can free up space in the conversation history.
Respond ONLY with the extracted context. Do not include any additional information, or text before or after the extracted context.

<messages>
Messages to summarize:
{messages}
</messages>"""


def _safe_cutoff_index(messages: list[AnyMessage], cutoff_index: int) -> int:
    """Nudge a cutoff index so it never separates an AIMessage's tool_calls from
    the ToolMessages answering them.

    Slicing `messages` by raw position can land the cutoff in the middle of a
    tool-call/tool-response sequence — e.g. the AIMessage that requested a
    tool call gets summarized away while the ToolMessage answering it is kept.
    Most providers reject that as an invalid message sequence (a tool
    response with no matching call) on the next real model call. If the
    message right at the cutoff is a ToolMessage, walk backward to find the
    AIMessage that produced it and move the cutoff there instead (summarizing
    a little less); if no matching AIMessage is found, walk forward past the
    ToolMessages instead (summarizing a little more).
    """
    if cutoff_index >= len(messages) or not isinstance(messages[cutoff_index], ToolMessage):
        return cutoff_index

    tool_call_ids: set[str] = set()
    idx = cutoff_index
    while idx < len(messages) and isinstance(messages[idx], ToolMessage):
        if messages[idx].tool_call_id:
            tool_call_ids.add(messages[idx].tool_call_id)
        idx += 1

    for i in range(cutoff_index - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, AIMessage) and msg.tool_calls:
            ai_tool_call_ids = {tc.get("id") for tc in msg.tool_calls if tc.get("id")}
            if tool_call_ids & ai_tool_call_ids:
                return i

    return idx


def make_summarize_node(model_provider: str | None = None, model_name: str | None = None):
    """Return the "summarize" node function for one graph build.

    Built fresh per request (like flow_nodes/supervisor.py's
    make_supervisor_node) rather than as a module-level singleton, since the
    summarizer's own provider/model are now caller-controlled too (main.py's
    ChatRequest.summarizer_model_provider/summarizer_model_name) — separate
    from the supervisor/specialists' model_provider/model_name, since the
    summarizer deliberately defaults to its own (usually cheaper) model
    (config["GEMINI_SUMMARIZER_MODEL"]), not whatever the main model is.
    """
    summarizer_model = build_summarizer_model(model_provider, model_name)

    async def maybe_summarize_node(state: TaskFlowState) -> dict:
        messages = state["messages"]

        if estimate_token_count(messages) <= TOKEN_TRIGGER:
            return {}

        cutoff_index = _safe_cutoff_index(messages, max(0, len(messages) - KEEP_LAST))
        to_summarize = messages[:cutoff_index]
        if not to_summarize:
            return {}

        # `get_buffer_string` renders each message as readable
        # "<Role>: <content>" text — `.format(messages=to_summarize)` alone would
        # instead interpolate Python's raw repr of the message objects
        # (`[HumanMessage(content='...', id='...'), ...]`), which is noisy and
        # wastes tokens for no benefit to the summarizer.
        formatted = _TASKFLOW_SUMMARY_PROMPT.format(
            messages=get_buffer_string(to_summarize, format="xml")
        )
        summary = await summarizer_model.ainvoke(formatted)

        return {
            "messages": [RemoveMessage(id=m.id) for m in to_summarize if m.id]
            + [HumanMessage(content=summary.content, additional_kwargs={"lc_source": "summarization"})]
        }

    return maybe_summarize_node
