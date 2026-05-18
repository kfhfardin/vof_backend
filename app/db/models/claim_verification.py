"""ClaimVerification - per-claim audit row for the F5 web verifier.

Phase 1 §F5: one row per (call, claim) processed by the verifier. Stores
the verdict (corroborated / unconfirmed / contradicted), the single web
evidence pair (url + snippet) and, when contradicted, optionally links to
the CorrectionIntake that surfaces the contradiction to the Manager.

The (workspace_id, call_id) composite index supports the per-call list
endpoint; (workspace_id, claim_subject) supports the brain-page lookup.

correction_intake_id FK + SET NULL ondelete are declared in migration
0010_phase_1_unified (the correction_intakes table is created in the same
migration).
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import Float, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey

VerificationStatus = Literal["corroborated", "unconfirmed", "contradicted"]


class ClaimVerification(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "claim_verifications"
    __table_args__ = (
        Index(
            "ix_claim_verifications_workspace_call",
            "workspace_id",
            "call_id",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("manager_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized per HLD: lets org-scoped reports avoid a workspace join.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    claim_subject: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    claim_predicate: Mapped[str] = mapped_column(String(128), nullable=False)
    claim_object: Mapped[str] = mapped_column(String(512), nullable=False)
    claim_source_utterance: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[VerificationStatus] = mapped_column(String(16), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    evidence_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    evidence_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    contradiction_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    correction_intake_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("correction_intakes.id", ondelete="SET NULL"),
        nullable=True,
    )
