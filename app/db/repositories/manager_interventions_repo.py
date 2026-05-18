"""ManagerIntervention repository (Phase 1 F7 - whisper only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InterventionMode, ManagerIntervention


class ManagerInterventionsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        call_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        mode: InterventionMode,
        started_at: datetime,
        payload: dict[str, Any],
    ) -> ManagerIntervention:
        row = ManagerIntervention(
            call_id=call_id,
            workspace_id=workspace_id,
            user_id=user_id,
            mode=mode,
            started_at=started_at,
            payload=payload or {},
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, intervention_id: UUID) -> ManagerIntervention | None:
        return await self.session.get(ManagerIntervention, intervention_id)

    async def list_for_call(self, call_id: UUID) -> list[ManagerIntervention]:
        result = await self.session.execute(
            select(ManagerIntervention)
            .where(ManagerIntervention.call_id == call_id)
            .order_by(ManagerIntervention.started_at.asc())
        )
        return list(result.scalars().all())

    async def mark_consumed(
        self,
        intervention_id: UUID,
        *,
        turn_number: int,
    ) -> ManagerIntervention | None:
        row = await self.get(intervention_id)
        if row is None:
            return None
        payload = dict(row.payload or {})
        payload["consumed_at_turn"] = turn_number
        row.payload = payload
        # SQLAlchemy doesn't auto-detect JSONB mutations; explicit re-assign above
        # is enough but we also flag to be safe.
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(row, "payload")
        await self.session.flush()
        return row
