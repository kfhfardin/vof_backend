"""Provenance repository."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Provenance, SourceType


class ProvenanceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        workspace_id: UUID,
        source_type: SourceType,
        source_id: UUID | None = None,
        extracted_by: str | None = None,
        confidence: float | None = None,
        cites: list[dict[str, Any]] | None = None,
        rationale: str | None = None,
        extracted_at: datetime | None = None,
    ) -> Provenance:
        p = Provenance(
            workspace_id=workspace_id,
            source_type=source_type,
            source_id=source_id,
            extracted_by=extracted_by,
            confidence=confidence,
            cites=cites or [],
            rationale=rationale,
            extracted_at=extracted_at or datetime.now(UTC),
        )
        self.session.add(p)
        await self.session.flush()
        return p

    async def get(self, provenance_id: UUID) -> Provenance | None:
        return await self.session.get(Provenance, provenance_id)
