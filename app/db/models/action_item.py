"""ActionItem - extracted-from-call task with a one-step approval gate.

Per Phase 1 LLD §F3: heuristic extractor (F2) writes rows as
`pending_approval`; Manager `/approve` flips to `approved`; the
dispatcher cron picks them up and runs the handler (scheduler or
email_drafter) via a Jinja-rendered draft + provider call.

No preview/confirm step. Approve = execute.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey

ActionItemStatus = Literal[
    "pending_approval",
    "needs_review",
    "approved",
    "done",
    "failed",
    "needs_reconnect",
    "rejected",
]

ActionItemHandler = Literal["scheduler", "email_drafter", "none"]


class ActionItem(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "action_items"

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
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("calls.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(String(), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    status: Mapped[ActionItemStatus] = mapped_column(
        String(32),
        nullable=False,
        default="pending_approval",
        server_default="pending_approval",
        index=True,
    )

    extracted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    handler: Mapped[ActionItemHandler] = mapped_column(
        String(32),
        nullable=False,
        default="none",
        server_default="none",
    )
    handler_outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    handler_outcome_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("call_artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    handler_executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handler_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    handler_error: Mapped[str | None] = mapped_column(String(), nullable=True)
