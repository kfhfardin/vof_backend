"""DecisionRequest repository.

`lock_for_update` is the load-bearing query - DecisionService uses it
on /respond so simultaneous WS + SMS replies don't both succeed.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DecisionClass, DecisionRequest, DecisionStatus, RespondedVia


class DecisionsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, decision_id: UUID) -> DecisionRequest | None:
        return await self.session.get(DecisionRequest, decision_id)

    async def lock_for_update(self, decision_id: UUID) -> DecisionRequest | None:
        result = await self.session.execute(
            select(DecisionRequest).where(DecisionRequest.id == decision_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        call_id: UUID,
        workspace_id: UUID,
        target_user_id: UUID,
        prompt: str,
        options: list[str],
        decision_class: DecisionClass,
        timeout_at: datetime | None,
        context: dict[str, Any] | None = None,
    ) -> DecisionRequest:
        d = DecisionRequest(
            call_id=call_id,
            workspace_id=workspace_id,
            target_user_id=target_user_id,
            prompt=prompt,
            options=options,
            decision_class=decision_class,
            timeout_at=timeout_at,
            status="open",
            context=context,
        )
        self.session.add(d)
        await self.session.flush()
        return d

    async def mark_answered(
        self,
        decision: DecisionRequest,
        *,
        response: str,
        responded_by_user_id: UUID,
        via: RespondedVia,
        responded_at: datetime,
    ) -> DecisionRequest:
        decision.status = "answered"
        decision.response = response
        decision.responded_by_user_id = responded_by_user_id
        decision.responded_via = via
        decision.responded_at = responded_at
        await self.session.flush()
        return decision

    async def mark_timed_out(self, decision: DecisionRequest, *, ended_at: datetime) -> DecisionRequest:
        decision.status = "timed_out"
        decision.responded_via = "timeout"
        decision.responded_at = ended_at
        await self.session.flush()
        return decision

    async def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        status: DecisionStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DecisionRequest]:
        stmt = (
            select(DecisionRequest)
            .where(DecisionRequest.workspace_id == workspace_id)
            .order_by(DecisionRequest.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            stmt = stmt.where(DecisionRequest.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_open_for_user(self, user_id: UUID) -> list[DecisionRequest]:
        result = await self.session.execute(
            select(DecisionRequest)
            .where(
                DecisionRequest.target_user_id == user_id,
                DecisionRequest.status == "open",
            )
            .order_by(DecisionRequest.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_missed_for_brief(
        self, workspace_id: UUID, *, since: datetime | None = None
    ) -> list[DecisionRequest]:
        """Decisions that timed out and haven't been surfaced in a brief yet.

        Phase 1 §D5 `dashboard_rollup` consumes this and stamps
        `surfaced_in_brief_at` after rendering. The skeleton lives in §C7
        so the column + query path are stable from day one.
        """
        stmt = select(DecisionRequest).where(
            DecisionRequest.workspace_id == workspace_id,
            DecisionRequest.status == "timed_out",
            DecisionRequest.surfaced_in_brief_at.is_(None),
        )
        if since is not None:
            stmt = stmt.where(DecisionRequest.responded_at >= since)
        stmt = stmt.order_by(DecisionRequest.responded_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_surfaced_in_brief(self, decision_ids: list[UUID], *, surfaced_at: datetime) -> int:
        """Phase 1 §D5 calls this after rendering. Returns rows updated."""
        if not decision_ids:
            return 0
        from sqlalchemy import update

        result = await self.session.execute(
            update(DecisionRequest)
            .where(
                DecisionRequest.id.in_(decision_ids),
                DecisionRequest.surfaced_in_brief_at.is_(None),
            )
            .values(surfaced_in_brief_at=surfaced_at)
        )
        rowcount = getattr(result, "rowcount", 0)
        return int(rowcount or 0)
