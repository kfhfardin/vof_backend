"""OrchestratorTool ABC + per-process registry.

A tool is something the LLM can invoke mid-turn. Phase 0 §C6 ships the
first real tool (request_manager_decision); §C8 will add request_correction
and fetch_account; Phase 1 §D2 adds mark_followup; end_call lives here too.

Invocation pattern in Phase 0 is marker-based: the LLM emits
`<<TOOL name {json}>>` in its output, the orchestrator's marker detector
parses it and dispatches via `ToolRegistry.dispatch()`. Upgrading to native
OpenAI tool-call streaming is a later polish - the tool contract here is
provider-agnostic so the upgrade doesn't touch tool code.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolContext:
    workspace_id: UUID
    call_id: UUID
    field_employee_id: UUID | None


@dataclass(frozen=True)
class ToolResult:
    """Returned by every tool. The orchestrator uses these fields to decide
    what to do next on the turn."""

    # Whether to emit a bridge chunk to AP before / instead of continuing
    # to stream more text from the LLM. The orchestrator pushes this as
    # the final NDJSON chunk if non-empty.
    bridge_text: str | None = None
    # Whether the turn should end after this tool (e.g. end_call).
    end_turn: bool = False
    # Whether to end the entire call (only end_call sets this).
    hangup: bool = False
    # Free-form data the LLM should see on the next turn (e.g. decision id).
    followup_context: dict[str, Any] | None = None


class OrchestratorTool(ABC):
    name: ClassVar[str]
    input_schema: ClassVar[type[BaseModel]]
    # LLM-visible description (used both in the prompt and for future
    # function-call schema generation).
    description: ClassVar[str]

    @abstractmethod
    async def run(self, ctx: ToolContext, inputs: BaseModel) -> ToolResult:
        """Execute. Validation has already happened by the registry."""


class _ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, OrchestratorTool] = {}

    def register(self, tool: OrchestratorTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> OrchestratorTool:
        if name not in self._tools:
            raise KeyError(f"tool {name!r} not registered (available: {sorted(self._tools)})")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> list[dict[str, Any]]:
        """Schemas for rendering into the orchestrator skill prompt."""
        out: list[dict[str, Any]] = []
        for name in sorted(self._tools):
            tool = self._tools[name]
            out.append(
                {
                    "name": name,
                    "description": tool.description,
                    "input_schema": tool.input_schema.model_json_schema(),
                }
            )
        return out

    async def dispatch(self, ctx: ToolContext, name: str, args: dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        validated = tool.input_schema.model_validate(args)
        return await tool.run(ctx, validated)


ToolRegistry = _ToolRegistry()


# ---- Marker helpers (used by app/orchestrator/tool_dispatch.py) ----

MARKER_OPEN = "<<TOOL "
MARKER_CLOSE = ">>"


def encode_tool_marker(name: str, args: dict[str, Any]) -> str:
    """Helper for tests / docs - the LLM should emit this shape."""
    return f"{MARKER_OPEN}{name} {json.dumps(args)}{MARKER_CLOSE}"
