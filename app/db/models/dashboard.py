"""DashboardSnapshot + SavedDashboardQuery - Phase 1 §F8.

The nightly `dashboard_rollup` mini-agent writes one row per
(workspace_id, snapshot_date, dimension[, key]) per day; the per-dimension
metrics blob is opaque JSONB tailored to the FE renderer for that dimension.

SavedDashboardQuery captures per-user pinned filters; the manager FE caps
pinned at 10 (enforced in the repo). The query is intentionally just
{dimension + filters} - the running of the query is a follow-up call to the
dimension endpoint.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey

DashboardDimension = Literal["overview", "rep", "account", "theme", "decision"]


class DashboardSnapshot(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "dashboard_snapshots"
    __table_args__ = (
        Index(
            "ix_dashboard_snapshots_ws_date_dim",
            "workspace_id",
            "snapshot_date",
            "dimension",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("manager_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    dimension: Mapped[DashboardDimension] = mapped_column(String(32), nullable=False, index=True)
    # e.g. field_employee_id for rep dim, slug for account/theme; null for overview rows.
    key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SavedDashboardQuery(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "saved_dashboard_queries"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("manager_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
