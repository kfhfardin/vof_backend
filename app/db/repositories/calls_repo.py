"""Call repository."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Call


class CallsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, call_id: UUID) -> Call | None:
        return await self.session.get(Call, call_id)

    async def get_by_agentphone_id(self, ap_call_id: str) -> Call | None:
        result = await self.session.execute(select(Call).where(Call.agentphone_call_id == ap_call_id))
        return result.scalar_one_or_none()

    async def list_in_progress(self, workspace_id: UUID) -> list[Call]:
        result = await self.session.execute(
            select(Call)
            .where(
                Call.workspace_id == workspace_id,
                Call.status.in_(["ringing", "in_progress"]),
            )
            .order_by(Call.started_at.desc())
        )
        return list(result.scalars().all())

    async def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Call]:
        stmt = (
            select(Call)
            .where(Call.workspace_id == workspace_id)
            .order_by(Call.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            stmt = stmt.where(Call.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        workspace_id: UUID,
        organization_id: UUID,
        agentphone_call_id: str,
        from_number: str | None,
        to_number: str | None,
        started_at: datetime,
        field_employee_id: UUID | None = None,
    ) -> Call:
        call = Call(
            workspace_id=workspace_id,
            organization_id=organization_id,
            agentphone_call_id=agentphone_call_id,
            from_number=from_number,
            to_number=to_number,
            field_employee_id=field_employee_id,
            started_at=started_at,
            status="in_progress",
        )
        self.session.add(call)
        await self.session.flush()
        return call

    async def mark_ended(
        self,
        call_id: UUID,
        *,
        ended_at: datetime,
        provider_summary: dict[str, Any] | None = None,
    ) -> Call:
        call = await self.get(call_id)
        if call is None:
            raise RuntimeError(f"call {call_id} not found")
        call.status = "ended"
        call.ended_at = ended_at
        if provider_summary is not None:
            call.provider_summary = provider_summary
        return call
