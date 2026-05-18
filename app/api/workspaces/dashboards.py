"""Dashboard endpoints - LLD §F8.

Surfaces:

  GET    /workspaces/{wid}/dashboards/daily_brief?date=YYYY-MM-DD
  GET    /workspaces/{wid}/dashboards/overview
  GET    /workspaces/{wid}/dashboards/reps        ?range=30d
  GET    /workspaces/{wid}/dashboards/accounts    ?range=30d
  GET    /workspaces/{wid}/dashboards/themes      ?range=30d
  GET    /workspaces/{wid}/dashboards/decisions   ?range=30d
  GET    /workspaces/{wid}/dashboards/queries
  POST   /workspaces/{wid}/dashboards/queries
  GET    /workspaces/{wid}/dashboards/queries/{qid}
  DELETE /workspaces/{wid}/dashboards/queries/{qid}

The "Resolve now" CTA lives in `app/api/workspaces/decisions.py` as
POST /workspaces/{wid}/decisions/{id}/resolve_now (kept under /decisions
so the FE sees one decision-action namespace).

The overview endpoint hits the App DB directly (no materialized view -
deliberately cut from F8 per LLD). The per-dimension trend endpoints read
the `DashboardSnapshot` rows the nightly rollup writes.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Call, DashboardSnapshot, DecisionRequest, SavedDashboardQuery
from app.db.repositories.dashboards_repo import (
    DashboardSnapshotsRepo,
    SavedQueriesRepo,
)
from app.deps import (
    CurrentUser,
    get_object_store,
    get_session,
    require_workspace_access,
)
from app.errors import Conflict, NotFound, Validation
from app.logging import get_logger
from app.schemas.dashboard import (
    CreateSavedQueryRequest,
    DailyBriefResponse,
    OverviewResponse,
    SavedQueryListResponse,
    SavedQueryResponse,
    SnapshotListResponse,
    SnapshotResponse,
)
from app.storage.base import ObjectStore

log = get_logger(__name__)

router = APIRouter(prefix="/workspaces/{workspace_id}/dashboards", tags=["dashboards"])


_MAX_PINNED = 10


# ---------------- Helpers ----------------


def _parse_range(range_str: str) -> tuple[date, date]:
    """Parse "30d" / "90d" / "7d" into (date_from, date_to). date_to is today
    (UTC); date_from = today - <N> days. We deliberately accept only the
    `<N>d` shape - explicit dates land in a follow-up if needed.
    """
    s = range_str.strip().lower()
    if not s.endswith("d"):
        raise Validation(f"unsupported range: {range_str!r}; expected e.g. '30d'")
    try:
        n = int(s[:-1])
    except ValueError as e:
        raise Validation(f"invalid range: {range_str!r}") from e
    if n <= 0 or n > 365:
        raise Validation(f"range out of bounds: {range_str!r}")
    today = datetime.now(UTC).date()
    return today - timedelta(days=n), today


def _snapshot_to_dto(row: DashboardSnapshot) -> SnapshotResponse:
    return SnapshotResponse(
        snapshot_date=row.snapshot_date,
        dimension=row.dimension,
        key=row.key,
        metrics=row.metrics or {},
        computed_at=row.computed_at,
    )


def _query_to_dto(row: SavedDashboardQuery) -> SavedQueryResponse:
    return SavedQueryResponse(
        id=row.id,
        workspace_id=row.workspace_id,
        user_id=row.user_id,
        name=row.name,
        dimension=row.dimension,
        filters=row.filters or {},
        pinned=row.pinned,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------- Daily brief ----------------


@router.get(
    "/daily_brief",
    response_model=DailyBriefResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def get_daily_brief(
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[ObjectStore, Depends(get_object_store)],
    date_str: Annotated[str | None, Query(alias="date")] = None,
) -> DailyBriefResponse:
    """Return the brief artifact for `date` (default: yesterday UTC).

    The brief artifact JSON lives in object storage; the lookup key is
    stamped onto the overview DashboardSnapshot for the date by the
    dashboard_rollup mini-agent.
    """
    if date_str:
        try:
            brief_date = date.fromisoformat(date_str)
        except ValueError as e:
            raise Validation(f"invalid date: {date_str!r}") from e
    else:
        brief_date = (datetime.now(UTC) - timedelta(days=1)).date()

    repo = DashboardSnapshotsRepo(session)
    snap = await repo.get_for_date(workspace_id, "overview", brief_date)
    if snap is None:
        raise NotFound(f"no brief for {brief_date.isoformat()}")
    metrics = snap.metrics or {}
    storage_key = metrics.get("brief_storage_key")
    if not storage_key:
        raise NotFound("brief artifact key not yet stamped (rollup may still be running)")
    try:
        blob = await storage.get(storage_key)
    except Exception as e:
        log.exception("daily_brief_blob_fetch_failed", key=storage_key)
        raise NotFound("brief artifact missing in object storage") from e
    payload = json.loads(blob.decode("utf-8"))
    return DailyBriefResponse.model_validate(payload)


# ---------------- Overview (direct query) ----------------


@router.get(
    "/overview",
    response_model=OverviewResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def overview(
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OverviewResponse:
    """Top-level KPIs - queried directly against the App DB (no mview).

    LLD explicitly cuts the materialized-view layer for Phase 1; if this
    becomes slow the endpoint contract is stable enough to swap in a
    mview-backed read path without FE changes.
    """
    now = datetime.now(UTC)
    today = now.date()

    today_call_count = int(
        (
            await session.execute(
                select(func.count(Call.id)).where(
                    Call.workspace_id == workspace_id,
                    func.date(func.timezone("UTC", Call.started_at)) == today,
                    Call.status == "ended",
                )
            )
        ).scalar_one()
        or 0
    )

    in_progress = int(
        (
            await session.execute(
                select(func.count(Call.id)).where(
                    Call.workspace_id == workspace_id,
                    Call.status.in_(["ringing", "in_progress"]),
                )
            )
        ).scalar_one()
        or 0
    )

    decisions_opened_today = int(
        (
            await session.execute(
                select(func.count(DecisionRequest.id)).where(
                    DecisionRequest.workspace_id == workspace_id,
                    func.date(func.timezone("UTC", DecisionRequest.created_at)) == today,
                )
            )
        ).scalar_one()
        or 0
    )

    decisions_open_now = int(
        (
            await session.execute(
                select(func.count(DecisionRequest.id)).where(
                    DecisionRequest.workspace_id == workspace_id,
                    DecisionRequest.status == "open",
                )
            )
        ).scalar_one()
        or 0
    )

    return OverviewResponse(
        workspace_id=workspace_id,
        as_of=now,
        today_call_count=today_call_count,
        in_progress_call_count=in_progress,
        decisions_opened_today=decisions_opened_today,
        decisions_open_now=decisions_open_now,
    )


# ---------------- Per-dimension trend endpoints ----------------


async def _list_dimension(
    workspace_id: UUID,
    session: AsyncSession,
    dimension: str,
    range_str: str,
) -> SnapshotListResponse:
    date_from, date_to = _parse_range(range_str)
    repo = DashboardSnapshotsRepo(session)
    rows = await repo.list_for_range(workspace_id, dimension, date_from, date_to)
    return SnapshotListResponse(
        workspace_id=workspace_id,
        dimension=dimension,
        date_from=date_from,
        date_to=date_to,
        snapshots=[_snapshot_to_dto(r) for r in rows],
    )


@router.get(
    "/reps",
    response_model=SnapshotListResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def reps_trend(
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    range_str: Annotated[str, Query(alias="range")] = "30d",
) -> SnapshotListResponse:
    return await _list_dimension(workspace_id, session, "rep", range_str)


@router.get(
    "/accounts",
    response_model=SnapshotListResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def accounts_trend(
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    range_str: Annotated[str, Query(alias="range")] = "30d",
) -> SnapshotListResponse:
    return await _list_dimension(workspace_id, session, "account", range_str)


@router.get(
    "/themes",
    response_model=SnapshotListResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def themes_trend(
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    range_str: Annotated[str, Query(alias="range")] = "30d",
) -> SnapshotListResponse:
    return await _list_dimension(workspace_id, session, "theme", range_str)


@router.get(
    "/decisions",
    response_model=SnapshotListResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def decisions_trend(
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    range_str: Annotated[str, Query(alias="range")] = "30d",
) -> SnapshotListResponse:
    return await _list_dimension(workspace_id, session, "decision", range_str)


# ---------------- Saved queries ----------------


@router.get(
    "/queries",
    response_model=SavedQueryListResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def list_queries(
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SavedQueryListResponse:
    repo = SavedQueriesRepo(session)
    rows = await repo.list_for_workspace(workspace_id)
    return SavedQueryListResponse(queries=[_query_to_dto(r) for r in rows])


@router.post(
    "/queries",
    response_model=SavedQueryResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def create_query(
    workspace_id: UUID,
    body: CreateSavedQueryRequest,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SavedQueryResponse:
    repo = SavedQueriesRepo(session)
    if body.pinned:
        pinned_count = await repo.count_pinned(workspace_id)
        if pinned_count >= _MAX_PINNED:
            raise Conflict(
                f"pinned_queries_cap_reached (max {_MAX_PINNED})",
                details={"pinned_count": pinned_count, "max": _MAX_PINNED},
            )
    row = await repo.create(
        workspace_id=workspace_id,
        user_id=user.id,
        name=body.name,
        dimension=body.dimension,
        filters=body.filters,
        pinned=body.pinned,
    )
    await session.commit()
    return _query_to_dto(row)


@router.get(
    "/queries/{query_id}",
    response_model=SavedQueryResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def run_query(
    workspace_id: UUID,
    query_id: Annotated[UUID, Path(...)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SavedQueryResponse:
    """Returns the query definition. The FE is expected to issue follow-up
    calls against the dimension endpoint with the saved filters applied.
    """
    repo = SavedQueriesRepo(session)
    row = await repo.get(query_id)
    if row is None or row.workspace_id != workspace_id:
        raise NotFound("saved query not found")
    return _query_to_dto(row)


@router.delete(
    "/queries/{query_id}",
    status_code=204,
    dependencies=[Depends(require_workspace_access)],
)
async def delete_query(
    workspace_id: UUID,
    query_id: Annotated[UUID, Path(...)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    repo = SavedQueriesRepo(session)
    row = await repo.get(query_id)
    if row is None or row.workspace_id != workspace_id:
        raise NotFound("saved query not found")
    await repo.delete(query_id)
    await session.commit()
    return None


