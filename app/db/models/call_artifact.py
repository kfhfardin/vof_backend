"""CallArtifact - a stored byproduct of a call (summary, transcript export,
action-items export, recording).

The blob itself lives in object storage; this row holds the metadata so the
FE can list/download without scanning S3.

Phase 0 §C11 produces one CallArtifact per call: kind=canonical_summary,
storage_key under workspaces/{wid}/calls/{call_id}/canonical_summary.json.
Phase 1 §D1 adds transcript + recording + action_items kinds.
"""

import uuid
from typing import Literal

from sqlalchemy import ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey

ArtifactKind = Literal[
    "canonical_summary",
    "transcript",
    "recording",
    "provider_summary",
    "action_items_export",
    "action_item_handler_outcome",   # F3 - one row per executed handler
    "daily_brief",                    # F8 - one row per daily brief
]


class CallArtifact(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "call_artifacts"

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
    kind: Mapped[ArtifactKind] = mapped_column(String(32), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
