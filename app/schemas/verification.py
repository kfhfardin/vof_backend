"""ClaimVerification DTOs (F5)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ClaimVerificationView(BaseModel):
    id: UUID
    workspace_id: UUID
    organization_id: UUID
    call_id: UUID
    claim_subject: str
    claim_predicate: str
    claim_object: str
    claim_source_utterance: str
    status: str
    confidence: float
    evidence_url: str | None
    evidence_snippet: str | None
    contradiction_detail: str | None
    correction_intake_id: UUID | None
    created_at: datetime


class ClaimVerificationListResponse(BaseModel):
    verifications: list[ClaimVerificationView]
