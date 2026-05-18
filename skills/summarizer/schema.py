"""Summarizer skill - Input + Output Pydantic schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TranscriptTurn(BaseModel):
    speaker: Literal["caller", "agent"]
    text: str
    ts: datetime


class CallerInfo(BaseModel):
    name: str | None = None
    role: str | None = None


class BrainContextHit(BaseModel):
    slug: str
    title: str
    snippet: str


class Input(BaseModel):
    call_id: str
    started_at: datetime
    caller: CallerInfo
    transcript: list[TranscriptTurn]
    provider_summary: str | None = None
    brain_context: list[BrainContextHit] = Field(default_factory=list)


class ExtractedEntity(BaseModel):
    type: Literal["person", "company", "product", "theme"]
    name: str
    # Slug hint - the brain_updater will fuzzy-resolve, but a clean hint
    # short-circuits the lookup.
    slug_hint: str | None = None


class Output(BaseModel):
    discussion: str = Field(min_length=1, max_length=4000)
    blockers: list[str] = Field(default_factory=list)
    extracted_entities: list[ExtractedEntity] = Field(default_factory=list)
    # v0.2 additions (Phase 1) — superset of v0.1; default empty so old callers
    # keep working if the LLM elides them.
    verbatim_quotes: list[str] = Field(default_factory=list, max_length=10)
    topics: list[str] = Field(default_factory=list, max_length=15)
