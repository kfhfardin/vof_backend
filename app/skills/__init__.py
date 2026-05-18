"""Skills runtime - loader + registry + LLM client.

Skill content (prompt.j2, schema.py, SKILL.md, fixtures, evals) lives in
the sibling `skills/` directory (top of repo). This package is the code
that finds those directories, parses them, and exposes them at runtime.
"""

from app.skills.base import LLMSkill, Skill, SkillContext, SkillRegistry
from app.skills.llm_client import (
    BedrockMessagesClient,
    FakeLLMClient,
    LLMClient,
    OpenAICompatClient,
    get_llm_client,
    set_llm_client,
)
from app.skills.loader import load_all_skills

__all__ = [
    "BedrockMessagesClient",
    "FakeLLMClient",
    "LLMClient",
    "LLMSkill",
    "OpenAICompatClient",
    "Skill",
    "SkillContext",
    "SkillRegistry",
    "get_llm_client",
    "load_all_skills",
    "set_llm_client",
]
