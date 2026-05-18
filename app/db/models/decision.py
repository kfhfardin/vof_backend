"""DecisionRequest - a mid-call ask from the Orchestrator to the Manager.

Three decision_classes (per HLD §5.5.3):
  - inline:  45s default timeout; Rep is mid-thread
  - bridged: 2m default timeout; can be deferred a few turns
  - async:   no live wait; surfaces post-call

Phase 0 always targets the Manager (target_user_id = Workspace.manager_user_id).
The schema accommodates delegation rotation (target_user_id is rotatable) so
Phase 1+ org-level delegation lights up without migration.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey

DecisionClass = Literal["inline", "bridged", "async"]
# `answered_late` lands with Phase 1 §F8: the Manager's "Resolve now" CTA on a
# timed-out decision transitions timed_out -> answered_late so audit/brief
# queries can tell a live answer from a post-hoc one. The DB CHECK constraint
# is widened in migration 0010_phase_1_unified.
DecisionStatus = Literal["open", "answered", "answered_late", "timed_out", "cancelled"]
RespondedVia = Literal["websocket", "sms", "timeout"]


class DecisionRequest(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "decision_requests"

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("manager_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    prompt: Mapped[str] = mapped_column(String(), nullable=False)
    options: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    decision_class: Mapped[DecisionClass] = mapped_column(String(16), nullable=False)
    timeout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[DecisionStatus] = mapped_column(
        String(16), nullable=False, default="open", server_default="open", index=True
    )
    response: Mapped[str | None] = mapped_column(String(), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    responded_via: Mapped[RespondedVia | None] = mapped_column(String(16), nullable=True)

    # `surfaced_in_brief_at` lands with §C7 / Phase 1 §D5; here from day one
    # so the timeout worker + brief generator don't need a follow-up migration.
    surfaced_in_brief_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Free-form context payload (e.g. original LLM rationale, account context
    # at time of ask) - stored alongside the decision for audit + replay.
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
