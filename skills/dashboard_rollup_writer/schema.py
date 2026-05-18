"""Dashboard Rollup Writer skill - Input + Output Pydantic schemas."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class MissedDecision(BaseModel):
    decision_id: str
    prompt: str
    call_id: str
    caller_name: str | None = None
    options: list[str] = Field(default_factory=list)
    timed_out_at_iso: str


class AccountMovement(BaseModel):
    slug: str
    title: str
    new_timeline_entries: int = 0
    new_blockers: list[str] = Field(default_factory=list)


class RepActivity(BaseModel):
    field_employee_id: str
    name: str
    call_count: int = 0
    top_topics: list[str] = Field(default_factory=list)


class StubEscalation(BaseModel):
    slug: str
    title: str
    mention_count: int = 0


class Input(BaseModel):
    workspace_id: UUID
    workspace_name: str
    brief_date: date
    call_count: int
    top_topics: list[str] = Field(default_factory=list)
    urgent_flags: list[str] = Field(default_factory=list)
    missed_decisions: list[MissedDecision] = Field(default_factory=list)
    account_movement: list[AccountMovement] = Field(default_factory=list)
    reps_in_motion: list[RepActivity] = Field(default_factory=list)
    stub_escalations: list[StubEscalation] = Field(default_factory=list)


class BriefSections(BaseModel):
    yesterday_at_a_glance: str = Field(min_length=1, max_length=2000)
    decisions_you_missed: str = Field(min_length=1, max_length=4000)
    account_movement: str = Field(min_length=1, max_length=3000)
    reps_in_motion: str = Field(min_length=1, max_length=3000)
    stub_to_real_escalations: str = Field(min_length=1, max_length=2000)


class Output(BaseModel):
    subject_line: str = Field(min_length=1, max_length=200)
    sections: BriefSections
