"""IntakeBufferItem - the Manager's intake records (onboarding + continuous use).

Per LLD §C2 - the same row shape covers form submissions, document uploads,
voice-intake transcript chunks, and Manager corrections. `purpose` tags
where in the lifecycle this item arrived (analytics only - behavior is
identical regardless of purpose).
"""

import uuid
from typing import Any, Literal

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey

IntakeSource = Literal["form", "upload", "voice_intake", "correction", "rep_email_followup"]
IntakePurpose = Literal["onboarding", "ongoing_update", "correction"]
IntakeStatus = Literal[
    "queued",
    "extracting",
    "classified",
    "ingested",
    "needs_review",
    "failed",
    "superseded",
    "deleted",
]


class IntakeBufferItem(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "intake_buffer_items"

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
    submitted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    source: Mapped[IntakeSource] = mapped_column(String(32), nullable=False)
    purpose: Mapped[IntakePurpose] = mapped_column(String(32), nullable=False)

    content_text: Mapped[str | None] = mapped_column(String(), nullable=True)
    content_blob_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    extractor_used: Mapped[str | None] = mapped_column(String(32), nullable=True)

    status: Mapped[IntakeStatus] = mapped_column(String(16), nullable=False, default="queued", index=True)
    classification: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    handler_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    superseded_by_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("intake_buffer_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    error: Mapped[str | None] = mapped_column(String(), nullable=True)
