"""Loads the TaskFlow agent's system prompts from prompts/templates/.

Keeping prompt text in its own .txt files means it can be edited by anyone
(not just someone comfortable editing Python) without touching code.

One prompt per specialist domain (agent/flow_nodes/specialist_agent.py) plus
one for the routing step (agent/flow_nodes/supervisor.py) — see
tool_groups.py's SPECIALIST_NAMES for the full list of valid domains.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_DOMAIN_FILES = {
    "task": "task_domain.txt",
    "team": "team_domain.txt",
    "workspace": "workspace_domain.txt",
    "user_admin": "user_admin_domain.txt",
    "knowledge": "knowledge_domain.txt",
}


@lru_cache(maxsize=1)
def _common_rules() -> str:
    return (_TEMPLATE_DIR / "agent_common.txt").read_text(encoding="utf-8").strip()


@lru_cache(maxsize=None)
def get_domain_system_prompt(domain: str) -> str:
    """Return the full system prompt for one specialist agent's domain.

    Each specialist gets its own short domain header (what it handles,
    tool-choice guidance specific to it) followed by the same shared rules
    (error handling, off-topic refusal, summary-context handling) every
    specialist needs — see agent/flow_nodes/supervisor.py for why the agent
    is split into domains at all.
    """
    domain_text = (_TEMPLATE_DIR / _DOMAIN_FILES[domain]).read_text(encoding="utf-8").strip()
    return f"{domain_text}\n\n{_common_rules()}"


@lru_cache(maxsize=1)
def get_supervisor_prompt() -> str:
    """Return the routing step's system prompt (no tools, structured output only)."""
    return (_TEMPLATE_DIR / "supervisor.txt").read_text(encoding="utf-8").strip()
