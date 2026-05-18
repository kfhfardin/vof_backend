"""Orchestrator skill - Input + Output Pydantic schemas.

Unlike other skills, the Orchestrator streams free-form text rather than
returning a single JSON object. Output here is a placeholder; the actual
hot path uses LLMClient.stream_chat() directly with the rendered prompt.
The skill loader still wants these classes defined for consistency.
"""

from typing import Any

from pydantic import BaseModel, Field


class TurnContext(BaseModel):
    """One brain or memory hit, normalized for the prompt."""

    source: str  # "caller_memory" | "brain"
    slug_or_id: str
    title: str
    snippet: str


class CallerSummary(BaseModel):
    name: str | None = None
    role: str | None = None
    team: str | None = None
    profiled: bool = False
    profile_summary: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)


class HistoryTurn(BaseModel):
    speaker: str  # "caller" | "agent"
    text: str
    ts: str  # ISO


class Input(BaseModel):
    workspace_name: str
    workspace_id: str
    call_id: str
    caller: CallerSummary
    rep_utterance: str = Field(min_length=0, max_length=20_000)
    conversation_history: list[HistoryTurn] = Field(default_factory=list)
    caller_hits: list[TurnContext] = Field(default_factory=list)
    brain_hits: list[TurnContext] = Field(default_factory=list)
    manager_whispers: list[str] = Field(default_factory=list)


class Output(BaseModel):
    """Placeholder - the Orchestrator streams; this is here for loader symmetry."""

    text: str
