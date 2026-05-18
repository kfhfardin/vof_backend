"""User - the auth principal.

All four roles are schema-supported from Phase 0 so the §C10 hierarchy
guard test can create stub org_admin / rep / viewer users and assert
they're rejected from endpoints they shouldn't reach. Only `manager`
is exposed in Phase 0 FE (HLD §5.2).
"""

import uuid
from typing import Literal

from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey

UserRole = Literal["manager", "org_admin", "rep", "viewer"]


class User(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Null for org_admin (spans an Org); set for manager / rep / viewer.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("manager_workspaces.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # Future: set when role=rep, links to FieldEmployee.
    # FieldEmployee model lands with §C2; for now nullable, no FK constraint
    # to avoid forward-dependency issues. The constraint is added in a later
    # migration when FieldEmployee ships.
    field_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        index=True,
    )

    email: Mapped[str] = mapped_column(String(254), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(16), nullable=False, index=True)

    front_end_push_token: Mapped[str | None] = mapped_column(String(256), nullable=True)
