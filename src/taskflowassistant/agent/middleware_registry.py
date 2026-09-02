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

middlewares: list = [
    SummarizationMiddleware(
        model=summarizer_model,
        # Tool-heavy turns here return sizeable JSON (a full Kanban board,
        # member lists, etc.), so 5000 tokens triggered summarization on
        # almost every multi-tool-call turn — raised to 8000/keep more
        # messages so it only kicks in for conversations that actually run
        # long, not routine 2-3-tool-call turns.
        trigger=("tokens", 8000),
        keep=("messages", 12),
        summary_prompt=_TASKFLOW_SUMMARY_PROMPT,
    ),
    ModelCallLimitMiddleware(
        thread_limit=config["MODEL_CALL_LIMIT_PER_THREAD"],
        run_limit=config["MODEL_CALL_LIMIT_PER_RUN"],
        exit_behavior="end",
    ),
]
