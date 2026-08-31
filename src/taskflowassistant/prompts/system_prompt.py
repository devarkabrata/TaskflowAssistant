"""Loads the agent's system prompt from prompts/templates/agent_system.txt.

Keeping the prompt text in its own .txt file means it can be edited by
anyone (not just someone comfortable editing Python) without touching code.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "agent_system.txt"


@lru_cache(maxsize=1)
def get_system_prompt() -> str:
    """Return the TaskFlow agent's system prompt as a plain string."""
    return _TEMPLATE_PATH.read_text(encoding="utf-8").strip()
