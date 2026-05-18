"""Intake buffer repository."""

from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IntakeBufferItem, IntakePurpose, IntakeSource, IntakeStatus


class IntakeRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_sha(self, workspace_id: UUID, sha256: str) -> IntakeBufferItem | None:
        result = await self.session.execute(
            select(IntakeBufferItem).where(
                and_(
                    IntakeBufferItem.workspace_id == workspace_id,
                    IntakeBufferItem.content_sha256 == sha256,
                    IntakeBufferItem.status != "deleted",
                )
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        workspace_id: UUID,
        organization_id: UUID,
        submitted_by_user_id: UUID,
        source: IntakeSource,
        purpose: IntakePurpose,
        content_text: str | None = None,
        content_blob_key: str | None = None,
        content_mime: str | None = None,
        content_filename: str | None = None,
        content_sha256: str | None = None,
    ) -> IntakeBufferItem:
        item = IntakeBufferItem(
            workspace_id=workspace_id,
            organization_id=organization_id,
            submitted_by_user_id=submitted_by_user_id,
            source=source,
            purpose=purpose,
            content_text=content_text,
            content_blob_key=content_blob_key,
            content_mime=content_mime,
            content_filename=content_filename,
            content_sha256=content_sha256,
            status="queued",
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def get(self, item_id: UUID) -> IntakeBufferItem | None:
        return await self.session.get(IntakeBufferItem, item_id)

    async def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        purpose: IntakePurpose | None = None,
        status: IntakeStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[IntakeBufferItem]:
        stmt = (
            select(IntakeBufferItem)
            .where(IntakeBufferItem.workspace_id == workspace_id)
            .order_by(IntakeBufferItem.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if purpose is not None:
            stmt = stmt.where(IntakeBufferItem.purpose == purpose)
        if status is not None:
            stmt = stmt.where(IntakeBufferItem.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        item_id: UUID,
        *,
        status: IntakeStatus | None = None,
        extractor_used: str | None = None,
        classification: dict[str, Any] | None = None,
        handler_result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> IntakeBufferItem:
        item = await self.get(item_id)
        if item is None:
            raise RuntimeError(f"intake item {item_id} not found")
        if status is not None:
            item.status = status
        if extractor_used is not None:
            item.extractor_used = extractor_used
        if classification is not None:
            item.classification = classification
        if handler_result is not None:
            item.handler_result = handler_result
        if error is not None:
            item.error = error
        await self.session.flush()
        return item

    async def mark_superseded(self, item_id: UUID, by_item_id: UUID) -> None:
        item = await self.get(item_id)
        if item is None:
            raise RuntimeError(f"intake item {item_id} not found")
        item.status = "superseded"
        item.superseded_by_item_id = by_item_id
        await self.session.flush()

    async def soft_delete(self, item_id: UUID) -> None:
        item = await self.get(item_id)
        if item is None:
            raise RuntimeError(f"intake item {item_id} not found")
        item.status = "deleted"
        item.content_blob_key = None  # blob removal happens in service
        await self.session.flush()
