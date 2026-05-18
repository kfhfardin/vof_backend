"""TranscriptFragment - one row per speaker turn within a Call.

Persisted as the Orchestrator processes each turn so post-call summarization
(§C11) and the multi-call live view (§C5) have a durable record. The session
state in Redis carries the same content but is non-durable (key may evict).
"""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import UUIDPrimaryKey

Speaker = Literal["caller", "agent"]


class TranscriptFragment(UUIDPrimaryKey, Base):
    __tablename__ = "transcript_fragments"

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
    speaker: Mapped[Speaker] = mapped_column(String(8), nullable=False)
    text: Mapped[str] = mapped_column(String(), nullable=False)
    # Monotonic per call - assigned by repo on insert.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
