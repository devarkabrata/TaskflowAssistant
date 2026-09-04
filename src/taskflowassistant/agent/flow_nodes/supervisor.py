"""Routes a fresh user turn to exactly one domain specialist. Runs exactly
ONCE per turn, always — never re-consulted afterward.

Binding all ~40 TaskFlow tools to one model call (the previous single-agent
design) meant the model had to read that entire schema on every turn, even
for "hi" — a real latency/accuracy tax, and worse on a lower-tier/thinking
model that now also has to reason about which of 40 tools (if any) applies.
This node instead makes one cheap, tools-free classification call
(structured output only, fixed at "minimal" thinking regardless of the
request's own thinking_level — same reasoning as flow_nodes/summarizer.py's
fixed "medium": routing is bookkeeping, not something worth spending the
caller's chosen reasoning budget on) to decide which specialist
(flow_nodes/specialist_agent.py) should handle the request. Only that one
specialist's own, much smaller, tool subset is ever bound to a model call.

An earlier version of this node was re-consulted after every specialist
finished, to freely judge "are we done, or does another domain need to
contribute?" — demonstrated (identical input, two different outcomes across
two live runs) to be an unreliable judgment call, and one that could loop
all the way to the per-run call cap on plain greetings. That's been replaced
with an EXPLICIT handoff mechanism instead (agent/handoff_tools.py): a
specialist that needs another domain calls a real `handoff_to_X` tool, and
graph_executor.py's `route_after_tools`/`route_after_summarize` route to
that domain directly — a deterministic string comparison, not a second
model judgment. This node never needs to be re-entered as a result, which is
also why it no longer needs its own call-limit guard: it always runs with
`llm_calls == 0` for this run.
"""

import json
from typing import Literal

from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

from taskflowassistant.agent.flow_nodes._identity import IDENTITY_BLOCK_TEMPLATE
from taskflowassistant.agent.message_utils import ensure_valid_trailing_turn, strip_thought_signatures
from taskflowassistant.agent.models.model_1 import build_model
from taskflowassistant.agent.schema.state import TaskFlowState
from taskflowassistant.prompts.system_prompt import get_supervisor_prompt

# Keep in sync with agent/tool_groups.py's SPECIALIST_NAMES — duplicated as a
# Literal here (rather than built dynamically from that tuple) purely so
# Pydantic/the model provider see a real enum in the structured-output schema.
RouteChoice = Literal["task", "team", "workspace", "user_admin", "knowledge"]


class _RouteDecision(BaseModel):
    specialist: RouteChoice = Field(..., description="Which specialist should handle this request.")


# Module-level singleton, like flow_nodes/summarizer.py's summarizer_model —
# built once per process, not once per request. "minimal" thinking is fixed
# here (not the caller's own thinking_level) because classifying into one of
# five buckets needs no real reasoning budget.
_router_model = build_model(thinking_level="minimal").with_structured_output(_RouteDecision)


async def supervisor_node(state: TaskFlowState) -> dict:
    prompt = get_supervisor_prompt()
    current_user = state.get("current_user")
    if current_user:
        prompt += IDENTITY_BLOCK_TEMPLATE.format(profile=json.dumps(current_user, indent=2))

    conversation = ensure_valid_trailing_turn(strip_thought_signatures(state["messages"]))
    messages = [SystemMessage(content=prompt), *conversation]
    decision: _RouteDecision = await _router_model.ainvoke(messages)

    return {
        "active_specialist": decision.specialist,
        "llm_calls": state.get("llm_calls", 0) + 1,
    }
