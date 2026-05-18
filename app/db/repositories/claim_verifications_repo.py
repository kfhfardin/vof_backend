"""ClaimVerification repository.

Backs the F5 web verifier mini-agent. Three read patterns:
  - list_for_call(call_id)           -> per-call audit endpoint
  - list_for_claim_subject(ws, sub)  -> per-brain-page endpoint
  - find_existing_corroborated(...)  -> freshness reuse (LLD §F5 edge cases:
    a claim corroborated within the last 30d is reused, no fresh fetch)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ClaimVerification, VerificationStatus


class ClaimVerificationsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        workspace_id: UUID,
        organization_id: UUID,
        call_id: UUID,
        claim_subject: str,
        claim_predicate: str,
        claim_object: str,
        claim_source_utterance: str,
        status: VerificationStatus,
        confidence: float,
        evidence_url: str | None = None,
        evidence_snippet: str | None = None,
        contradiction_detail: str | None = None,
        correction_intake_id: UUID | None = None,
    ) -> ClaimVerification:
        row = ClaimVerification(
            workspace_id=workspace_id,
            organization_id=organization_id,
            call_id=call_id,
            claim_subject=claim_subject,
            claim_predicate=claim_predicate,
            claim_object=claim_object,
            claim_source_utterance=claim_source_utterance,
            status=status,
            confidence=confidence,
            evidence_url=evidence_url,
            evidence_snippet=evidence_snippet,
            contradiction_detail=contradiction_detail,
            correction_intake_id=correction_intake_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_call(self, call_id: UUID) -> list[ClaimVerification]:
        result = await self.session.execute(
            select(ClaimVerification)
            .where(ClaimVerification.call_id == call_id)
            .order_by(ClaimVerification.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_for_claim_subject(
        self,
        workspace_id: UUID,
        claim_subject: str,
    ) -> list[ClaimVerification]:
        result = await self.session.execute(
            select(ClaimVerification)
            .where(
                ClaimVerification.workspace_id == workspace_id,
                ClaimVerification.claim_subject == claim_subject,
            )
            .order_by(ClaimVerification.created_at.desc())
        )
        return list(result.scalars().all())

    async def find_existing_corroborated(
        self,
        workspace_id: UUID,
        claim_subject: str,
        claim_predicate: str,
        claim_object: str,
        within_days: int = 30,
    ) -> ClaimVerification | None:
        cutoff = datetime.now(UTC) - timedelta(days=within_days)
        result = await self.session.execute(
            select(ClaimVerification)
            .where(
                ClaimVerification.workspace_id == workspace_id,
                ClaimVerification.claim_subject == claim_subject,
                ClaimVerification.claim_predicate == claim_predicate,
                ClaimVerification.claim_object == claim_object,
                ClaimVerification.status == "corroborated",
                ClaimVerification.created_at >= cutoff,
            )
            .order_by(ClaimVerification.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
