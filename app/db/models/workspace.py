"""ManagerWorkspace - the unit of isolation.

One Manager, one Workspace Brain, one AgentPhone number, one roster of
Field Reps. workspace_id is the canonical scope column on every
workspace-owned entity (HLD §2.1, §5.2).

The provisioning_state column captures the §C1 commit-then-side-effect
pattern: signup commits the row immediately, then AP number provisioning
+ brain schema creation happen async. State flows pending -> number_pending
-> ready, or -> failed.
"""

import uuid
from typing import Any, Literal

from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey
from app.db.models.organization import Organization

ProvisioningState = Literal["pending", "number_pending", "ready", "failed"]


class ManagerWorkspace(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "manager_workspaces"
    __table_args__ = (UniqueConstraint("primary_number", name="uq_manager_workspaces_primary_number"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # FK on the User side (added below) - declared here as nullable to avoid the
    # chicken-and-egg between the two tables; the §C1 service tightens this.
    manager_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", use_alter=True),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Empty until AP number provisioning completes (§C1).
    primary_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agentphone_agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agentphone_number_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    provisioning_state: Mapped[ProvisioningState] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
    )

    # Workspace-level settings (timeouts, retention, defaults).
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # F6 email surface - AgentMail per-Workspace inbox (Phase 1).
    email_inbox_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_inbox_addr: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    organization: Mapped[Organization] = relationship("Organization")
