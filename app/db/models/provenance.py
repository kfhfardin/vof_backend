"""Provenance - the audit record attached to every Brain write.

Per HLD §9.1 every BrainPage / BrainEdge / CallerBrain entry carries a
provenance row. Phase 0 ships per-page provenance only (per-claim is §14.2
open).

Lives in the app DB so it can be looked up from API endpoints without
hopping into the per-workspace brain schema. Brain pages reference it
by UUID without an enforced FK (cross-DB FKs don't work in Postgres);
the brain provider validates the provenance row exists before writing.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import UUIDPrimaryKey

SourceType = Literal[
    "manager_form",
    "manager_upload",
    "manager_voice_intake",
    "manager_correction",
    "field_call",
    "automated_extraction",
    "external_research",
    "system_seed",
]


class Provenance(UUIDPrimaryKey, Base):
    __tablename__ = "provenance"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("manager_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[SourceType] = mapped_column(String(32), nullable=False, index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    extracted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    cites: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # Free-form rationale (e.g. classifier reasoning, Manager correction rationale).
    rationale: Mapped[str | None] = mapped_column(String(), nullable=True)
