"""Call - one phone call lifecycle.

Created on the first webhook for a new AP callId; updated on subsequent
webhooks until `agent.call_ended` arrives. provider_summary holds the
AP-side post-call summary (HLD §11.2.1 - signal-only; our `summarizer`
mini-agent produces the canonical one in §C11).
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey

CallStatus = Literal["ringing", "in_progress", "ended", "failed"]


class Call(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "calls"
    __table_args__ = (UniqueConstraint("agentphone_call_id", name="uq_calls_agentphone_call_id"),)

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
    field_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("field_employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    agentphone_call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    from_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_number: Mapped[str | None] = mapped_column(String(32), nullable=True)

    status: Mapped[CallStatus] = mapped_column(
        String(16), nullable=False, default="ringing", server_default="ringing", index=True
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set when AP delivers the recording URL (asynchronously after call.ended).
    recording_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Object-storage key for the assembled transcript artifact (§D1 lands the artifact;
    # the column exists from day one for forward compat).
    transcript_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # AP's post-call summary (HLD §11.2.1). Our canonical summary is built by
    # the summarizer mini-agent in §C11 and stored as a CallArtifact (§D1).
    provider_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
