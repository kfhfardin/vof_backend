"""EmailMessage repository.

Per Phase 1 LLD §F6: backs the email_delivery mini-agent's outbound
idempotency check and the email_reply_handler's parent-row lookup
(In-Reply-To / References header correlation).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    EmailMessage,
    EmailProviderName,
    EmailRecipientClass,
    EmailTriggerKind,
)


class EmailMessagesRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        workspace_id: UUID,
        organization_id: UUID,
        provider: EmailProviderName,
        provider_message_id: str,
        provider_thread_id: str,
        trigger_kind: EmailTriggerKind,
        trigger_ref_id: UUID,
        recipient_class: EmailRecipientClass,
        recipient_addr: str,
        sent_at: datetime,
        correlation_idempotency_key: str,
    ) -> EmailMessage:
        row = EmailMessage(
            workspace_id=workspace_id,
            organization_id=organization_id,
            provider=provider,
            provider_message_id=provider_message_id,
            provider_thread_id=provider_thread_id,
            trigger_kind=trigger_kind,
            trigger_ref_id=trigger_ref_id,
            recipient_class=recipient_class,
            recipient_addr=recipient_addr,
            sent_at=sent_at,
            correlation_idempotency_key=correlation_idempotency_key,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def exists_by_idem(self, key: str) -> bool:
        result = await self.session.execute(
            select(EmailMessage.id).where(EmailMessage.correlation_idempotency_key == key).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def find_by_provider_message_ids(self, ids: list[str]) -> list[EmailMessage]:
        if not ids:
            return []
        result = await self.session.execute(
            select(EmailMessage).where(EmailMessage.provider_message_id.in_(ids))
        )
        return list(result.scalars().all())

    async def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EmailMessage]:
        result = await self.session.execute(
            select(EmailMessage)
            .where(EmailMessage.workspace_id == workspace_id)
            .order_by(EmailMessage.sent_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
