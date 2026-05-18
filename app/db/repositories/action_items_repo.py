"""ActionItem repository (Phase 1 F3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActionItem, ActionItemHandler, ActionItemStatus


class ActionItemsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        workspace_id: UUID,
        organization_id: UUID,
        call_id: UUID | None,
        title: str,
        description: str | None,
        due_at: datetime | None,
        payload: dict[str, Any],
        status: ActionItemStatus = "pending_approval",
        extracted_by: str | None = None,
        confidence: float | None = None,
        handler: ActionItemHandler = "none",
    ) -> ActionItem:
        item = ActionItem(
            workspace_id=workspace_id,
            organization_id=organization_id,
            call_id=call_id,
            title=title,
            description=description,
            due_at=due_at,
            payload=payload or {},
            status=status,
            extracted_by=extracted_by,
            confidence=confidence,
            handler=handler,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def get(self, action_item_id: UUID) -> ActionItem | None:
        return await self.session.get(ActionItem, action_item_id)

    async def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        status: ActionItemStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ActionItem]:
        stmt = (
            select(ActionItem)
            .where(ActionItem.workspace_id == workspace_id)
            .order_by(ActionItem.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            stmt = stmt.where(ActionItem.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        item: ActionItem,
        *,
        status: ActionItemStatus,
    ) -> ActionItem:
        item.status = status
        await self.session.flush()
        return item

    async def update_handler_outcome(
        self,
        item: ActionItem,
        *,
        status: ActionItemStatus,
        outcome: dict[str, Any] | None = None,
        artifact_id: UUID | None = None,
        executed_at: datetime | None = None,
        error: str | None = None,
        attempts: int | None = None,
    ) -> ActionItem:
        item.status = status
        if outcome is not None:
            item.handler_outcome = outcome
        if artifact_id is not None:
            item.handler_outcome_artifact_id = artifact_id
        if executed_at is not None:
            item.handler_executed_at = executed_at
        if error is not None:
            item.handler_error = error
        if attempts is not None:
            item.handler_attempts = attempts
        await self.session.flush()
        return item

    async def list_approved_with_handler(
        self,
        workspace_id: UUID,
        *,
        limit: int = 50,
    ) -> list[ActionItem]:
        stmt = (
            select(ActionItem)
            .where(
                ActionItem.workspace_id == workspace_id,
                ActionItem.status == "approved",
                ActionItem.handler != "none",
            )
            .order_by(ActionItem.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
