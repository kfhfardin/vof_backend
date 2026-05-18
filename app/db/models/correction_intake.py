"""CorrectionIntake - the Manager-review queue for inbound corrections.

A CorrectionIntake is the staging row that lands BEFORE the CorrectionService
(`app/services/corrections.py`) is applied. The Manager reviews intakes and
chooses what to do with each one (apply / reject / edit-then-apply).

Origins:
  - manager:                manual Manager submission via FE
  - rep_callback:           a Rep calls back to correct something
  - system_web_verifier:    F5 raised a contradiction between a call claim and the web
  - manager_email_reply:    F6 detected a Manager reply on an outbound email

The `payload` JSONB carries origin-specific context (claim, evidence_url,
reply_body, etc.).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey

CorrectionOrigin = Literal[
    "manager",
    "rep_callback",
    "system_web_verifier",
    "manager_email_reply",
]
CorrectionIntakeStatus = Literal["open", "applied", "rejected", "dismissed"]


class CorrectionIntake(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "correction_intakes"

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
    target_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    origin: Mapped[CorrectionOrigin] = mapped_column(String(32), nullable=False, index=True)

    # Free-form ref to the upstream object: call_id, email_message_id, brief_id, etc.
    source_ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[CorrectionIntakeStatus] = mapped_column(
        String(16), nullable=False, default="open", server_default="open", index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
