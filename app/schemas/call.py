"""Call + transcript DTOs."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CallSummary(BaseModel):
    id: UUID
    workspace_id: UUID
    field_employee_id: UUID | None
    agentphone_call_id: str
    from_number: str | None
    to_number: str | None
    status: str
    started_at: datetime
    ended_at: datetime | None


class CallListResponse(BaseModel):
    calls: list[CallSummary]
    limit: int
    offset: int


class TranscriptFragmentDTO(BaseModel):
    id: UUID
    seq: int
    speaker: str
    text: str
    ts: datetime


class CallTranscriptResponse(BaseModel):
    call_id: UUID
    fragments: list[TranscriptFragmentDTO]
