"""Dashboard snapshot + saved-query repositories.

Per LLD §F8: one `DashboardSnapshot` row per (workspace, date, dimension[, key]);
the `SavedDashboardQuery` rows are per-user pinned filters capped at 10.

The bulk-create path is used by the nightly `dashboard_rollup` mini-agent,
which writes overview + per-rep + per-account + per-theme + per-decision rows
in a single transaction. `list_for_range` powers the dashboard endpoints
(`/dashboards/reps`, `/dashboards/accounts`, etc.).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DashboardSnapshot, SavedDashboardQuery


class DashboardSnapshotsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_create(self, snapshots: Sequence[DashboardSnapshot]) -> int:
        """Add many snapshot rows; flush so callers can read them in the same tx."""
        if not snapshots:
            return 0
        self.session.add_all(list(snapshots))
        await self.session.flush()
        return len(snapshots)

    async def list_for_range(
        self,
        workspace_id: UUID,
        dimension: str,
        date_from: date,
        date_to: date,
        *,
        key: str | None = None,
    ) -> list[DashboardSnapshot]:
        stmt = (
            select(DashboardSnapshot)
            .where(
                DashboardSnapshot.workspace_id == workspace_id,
                DashboardSnapshot.dimension == dimension,
                DashboardSnapshot.snapshot_date >= date_from,
                DashboardSnapshot.snapshot_date <= date_to,
            )
            .order_by(DashboardSnapshot.snapshot_date.asc())
        )
        if key is not None:
            stmt = stmt.where(DashboardSnapshot.key == key)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_for_date(
        self,
        workspace_id: UUID,
        dimension: str,
        snapshot_date: date,
        *,
        key: str | None = None,
    ) -> DashboardSnapshot | None:
        stmt = select(DashboardSnapshot).where(
            DashboardSnapshot.workspace_id == workspace_id,
            DashboardSnapshot.dimension == dimension,
            DashboardSnapshot.snapshot_date == snapshot_date,
        )
        if key is not None:
            stmt = stmt.where(DashboardSnapshot.key == key)
        stmt = stmt.order_by(DashboardSnapshot.computed_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class SavedQueriesRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        name: str,
        dimension: str,
        filters: dict[str, Any],
        pinned: bool = False,
    ) -> SavedDashboardQuery:
        row = SavedDashboardQuery(
            workspace_id=workspace_id,
            user_id=user_id,
            name=name,
            dimension=dimension,
            filters=filters,
            pinned=pinned,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, query_id: UUID) -> SavedDashboardQuery | None:
        return await self.session.get(SavedDashboardQuery, query_id)

    async def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        user_id: UUID | None = None,
    ) -> list[SavedDashboardQuery]:
        stmt = (
            select(SavedDashboardQuery)
            .where(SavedDashboardQuery.workspace_id == workspace_id)
            .order_by(
                SavedDashboardQuery.pinned.desc(),
                SavedDashboardQuery.created_at.desc(),
            )
        )
        if user_id is not None:
            stmt = stmt.where(SavedDashboardQuery.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, query_id: UUID) -> bool:
        result = await self.session.execute(
            delete(SavedDashboardQuery).where(SavedDashboardQuery.id == query_id)
        )
        rowcount = getattr(result, "rowcount", 0) or 0
        return int(rowcount) > 0

    async def count_pinned(self, workspace_id: UUID, *, user_id: UUID | None = None) -> int:
        from sqlalchemy import func

        stmt = select(func.count()).select_from(SavedDashboardQuery).where(
            SavedDashboardQuery.workspace_id == workspace_id,
            SavedDashboardQuery.pinned.is_(True),
        )
        if user_id is not None:
            stmt = stmt.where(SavedDashboardQuery.user_id == user_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)
