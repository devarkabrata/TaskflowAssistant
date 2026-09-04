"""Explicit handoff tools — how one specialist hands a request to another
domain without any LLM re-classifying the decision afterward.

The tool itself does almost nothing: calling `handoff_to_team` just produces
a `ToolMessage(name="handoff_to_team", ...)` like any other tool call. All
the actual routing lives in graph_executor.py's `route_after_tools` and
`route_after_summarize`, which read that tool NAME (plain string comparison,
no model involved) to decide which specialist runs next. This is the
"explicit handoff" pattern (see OpenAI's Swarm/Agents SDK, LangGraph's own
`langgraph-supervisor` library) — deliberately chosen over having the
supervisor re-classify after every specialist, which was demonstrated (see
flow_nodes/supervisor.py's git history) to be unreliable and to cost a real
model call for a decision the tool call already made unambiguously.
"""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

HANDOFF_TOOL_PREFIX = "handoff_to_"


class HandoffInput(BaseModel):
    reason: str = Field(
        ...,
        description="A short note on what still needs to be done — the next specialist sees this plus the full conversation so far.",
    )


def _make_one_handoff_tool(target_domain: str) -> StructuredTool:
    def _handoff(reason: str) -> str:
        return f"Handing off to the {target_domain} specialist: {reason}"

    return StructuredTool.from_function(
        func=_handoff,
        name=f"{HANDOFF_TOOL_PREFIX}{target_domain}",
        description=(
            f"Call this when YOUR part of the request is done but it also needs the "
            f"{target_domain} specialist's help — do not try to answer for that domain "
            f"yourself. Give a short `reason` describing what's still needed."
        ),
        args_schema=HandoffInput,
    )


def make_handoff_tools(own_domain: str, all_domains: tuple[str, ...]) -> list[StructuredTool]:
    """Return one `handoff_to_X` tool for every domain other than `own_domain`."""
    return [_make_one_handoff_tool(domain) for domain in all_domains if domain != own_domain]
