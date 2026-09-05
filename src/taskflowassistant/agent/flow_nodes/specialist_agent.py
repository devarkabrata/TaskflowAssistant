"""Builds one domain-scoped specialist agent node.

Each specialist is the same agent<->tools loop shape the old single agent
used before this file existed, just with only its own domain's tools bound
to the model (agent/tool_groups.py) instead of all ~40 at once. Which
specialist runs for a given turn is
decided once by flow_nodes/supervisor.py; graph_executor.py builds one of
these nodes per domain name in agent/tool_groups.py's SPECIALIST_NAMES.
"""

import json

from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool

from taskflowassistant.agent.flow_nodes._identity import IDENTITY_BLOCK_TEMPLATE
from taskflowassistant.agent.message_utils import (
    ensure_non_empty_tool_content,
    ensure_valid_trailing_turn,
    strip_thought_signatures,
)
from taskflowassistant.agent.models.model_1 import build_model, with_connection_retry
from taskflowassistant.agent.schema.state import TaskFlowState
from taskflowassistant.prompts.system_prompt import get_domain_system_prompt


def make_specialist_node(
    domain: str,
    tools: list[BaseTool],
    thinking_level: str | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
):
    """Return the agent node function for one specialist domain.

    `tools` must already be scoped to this domain (see
    tools_registry.py's get_tool_bundle) — this function only builds the
    node, it doesn't decide what belongs in it. `model_provider`/`model_name`
    come from the same POST /chat payload as `thinking_level` (see
    agent/models/model_1.py) — every specialist for a given turn shares the
    caller's one choice of provider/model.
    """
    model_with_tools = with_connection_retry(build_model(thinking_level, model_provider, model_name).bind_tools(tools))
    system_prompt = get_domain_system_prompt(domain)

    async def specialist_node(state: TaskFlowState) -> dict:
        prompt = system_prompt
        current_user = state.get("current_user")
        if current_user:
            prompt += IDENTITY_BLOCK_TEMPLATE.format(profile=json.dumps(current_user, indent=2))

        conversation = ensure_valid_trailing_turn(
            ensure_non_empty_tool_content(strip_thought_signatures(state["messages"]))
        )
        messages = [SystemMessage(content=prompt), *conversation]
        response = await model_with_tools.ainvoke(messages)
        # `llm_calls` is `UntrackedValue` (last-value-wins, not summed) — we
        # must add 1 to the current count ourselves, not just report "1".
        return {"messages": [response], "llm_calls": state.get("llm_calls", 0) + 1}

    return specialist_node
