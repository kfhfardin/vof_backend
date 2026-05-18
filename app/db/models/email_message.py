"""EmailMessage - audit row for every outbound email.

Per Phase 1 LLD §F6: one row per send, regardless of provider
(AgentMail-hosted Workspace inbox vs Gmail via the personal-mailbox
OAuth route). The `correlation_idempotency_key` UNIQUE constraint is
the dedupe seam: arq retries against the same (workspace, trigger_kind,
trigger_ref_id, recipient_class, recipient_addr) tuple resolve to a
single send.

Inbound replies are correlated via `provider_message_id` /
`provider_thread_id` (the email_reply_handler looks parent rows up by
In-Reply-To / References header values).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey

EmailProviderName = Literal["agentmail", "oauth_personal"]
EmailTriggerKind = Literal[
    "post_call_summary",
    "daily_brief",
    "missed_decisions",
    "action_item_handler",
]
EmailRecipientClass = Literal["manager", "rep", "external_customer"]


class EmailMessage(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "email_messages"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("manager_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    provider: Mapped[EmailProviderName] = mapped_column(String(32), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    provider_thread_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)

    trigger_kind: Mapped[EmailTriggerKind] = mapped_column(String(64), nullable=False)
    # Polymorphic ref: call_id / brief_id / action_item_id depending on trigger_kind.
    # No FK by design.
    trigger_ref_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    recipient_class: Mapped[EmailRecipientClass] = mapped_column(String(32), nullable=False)
    recipient_addr: Mapped[str] = mapped_column(String(320), nullable=False)

    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    correlation_idempotency_key: Mapped[str] = mapped_column(
        String(256), nullable=False, unique=True, index=True
    )
