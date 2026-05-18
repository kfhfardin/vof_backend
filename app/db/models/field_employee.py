"""FieldEmployee - a member of the Manager's team (caller + data subject).

Phase 0: data subject + caller identity only. Phase 1+ adds a User row with
role=rep linked here via field_employees.user_id (and User.field_employee_id).
The FK in both directions is added once both tables exist; for now we hold
the column nullable and skip the FK to avoid forward-dependency.

See HLD §2.1 / §5.2 / §6 and LLD §C3.
"""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey


class FieldEmployee(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "field_employees"
    __table_args__ = (UniqueConstraint("workspace_id", "phone", name="uq_field_employees_workspace_phone"),)

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
    # Reserved for Phase 1+ rep-side User accounts. No FK constraint yet
    # (added when User.field_employee_id FK closes the loop).
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)  # E.164
    role: Mapped[str | None] = mapped_column(String(120), nullable=True)
    team: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # `profiled=False` means the Rep was captured dynamically during a call
    # via the profiling sub-flow (LLD §C3) - the Manager hasn't approved them
    # to the roster yet.
    profiled: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")

    # Free-form Manager-seeded notes about this Rep (§7.1.2 caller-style intake).
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Note: per-caller Supermemory isolation is via containerTags - we tag each
    # memory with [f"caller_{id}", f"workspace_{workspace_id}"] at write time
    # (see app/memory/base.py::container_tags_for). No column stored here -
    # both tags are pure derivations of (workspace_id, id) on this row.
