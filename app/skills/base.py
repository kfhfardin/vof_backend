"""Skill base + registry + LLMSkill default impl.

Per LLD §A10 / §C9: every prompt is a directory on disk under skills/<name>/.
The loader (app/skills/loader.py) walks those directories, parses SKILL.md
frontmatter, compiles prompt.j2, and registers an LLMSkill for each.

A skill is callable like:
    out = await SkillRegistry.get("classifier").run(inputs, ctx)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel


@dataclass
class SkillContext:
    """Runtime context handed to every skill invocation."""

    workspace_id: UUID | None = None
    request_id: str | None = None
    # Free-form bag for skill-specific knobs (e.g. roster, known_accounts).
    extra: dict[str, Any] = field(default_factory=dict)


class Skill(ABC):
    name: ClassVar[str] = "unnamed"
    version: ClassVar[str] = "0.0.0"
    model: ClassVar[str] = ""
    input_schema: ClassVar[type[BaseModel]]
    output_schema: ClassVar[type[BaseModel]]
    quality_bar: ClassVar[str | None] = None

    @abstractmethod
    async def run(self, inputs: BaseModel, ctx: SkillContext) -> BaseModel: ...


class LLMSkill(Skill):
    """Default skill impl: renders prompt.j2 with inputs, calls LLM in JSON mode,
    validates against output_schema, retries once on schema failure.
    """

    def __init__(
        self,
        *,
        name: str,
        version: str,
        model: str,
        input_schema: type[BaseModel],
        output_schema: type[BaseModel],
        prompt_path: Path,
        quality_bar: str | None = None,
    ) -> None:
        self.name = name  # type: ignore[misc]
        self.version = version  # type: ignore[misc]
        self.model = model  # type: ignore[misc]
        self.input_schema = input_schema  # type: ignore[misc]
        self.output_schema = output_schema  # type: ignore[misc]
        self.quality_bar = quality_bar  # type: ignore[misc]
        self.prompt_path = prompt_path
        self._env = Environment(
            loader=FileSystemLoader(prompt_path.parent),
            undefined=StrictUndefined,
            autoescape=False,
        )
        self._template = self._env.get_template(prompt_path.name)

    def render_prompt(self, inputs: BaseModel, ctx: SkillContext) -> str:
        return self._template.render(
            inputs=inputs,
            ctx=ctx,
            **inputs.model_dump(),
            **ctx.extra,
        )

    async def run(self, inputs: BaseModel, ctx: SkillContext) -> BaseModel:
        from app.skills.llm_client import get_llm_client

        prompt = self.render_prompt(inputs, ctx)
        client = get_llm_client()
        # Two-shot: validate once, retry once with the prior failure as feedback
        attempt_errors: list[str] = []
        for attempt in range(2):
            messages: list[dict[str, str]] = []
            sys_part = (
                "You are a strict, JSON-emitting function. Reply with ONLY JSON conforming to the schema. "
                "No prose, no markdown fences."
            )
            if attempt_errors:
                sys_part += (
                    f"\n\nPrevious attempt failed validation: {attempt_errors[-1]}\n"
                    "Return JSON that satisfies the schema exactly."
                )
            messages.append({"role": "system", "content": sys_part})
            messages.append({"role": "user", "content": prompt})
            raw = await client.complete_json(model=self.model, messages=messages)
            try:
                parsed = self.output_schema.model_validate_json(raw)
                return parsed
            except Exception as e:
                attempt_errors.append(f"{type(e).__name__}: {e}")
                if attempt == 1:
                    raise RuntimeError(
                        f"skill {self.name}@{self.version} produced invalid JSON after retry: {attempt_errors}"
                    ) from e
        # Unreachable, but mypy needs it
        raise RuntimeError("unreachable")


class _SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if skill.name in self._skills:
            raise ValueError(f"skill {skill.name!r} already registered")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        if name not in self._skills:
            raise KeyError(f"skill {name!r} not registered (available: {sorted(self._skills)})")
        return self._skills[name]

    def list(self) -> list[str]:
        return sorted(self._skills)

    def clear(self) -> None:
        self._skills.clear()


SkillRegistry = _SkillRegistry()
