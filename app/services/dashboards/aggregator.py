"""Per-day rollup intermediates for the dashboard mini-agent (LLD §F8).

Splits cleanly into three steps:

  1. `compute_aggregate` queries the App DB for the day's intermediates -
     call count, missed decisions, per-rep activity. Account movement, top
     topics, and stub escalations are placeholders (TODO when F4 brain
     integration lands).
  2. `write_snapshots` materialises the rollup into one DashboardSnapshot
     row per dimension (overview + N rep rows + N account rows + N theme
     rows + N decision rows). Same transaction as the brief artifact write
     in `app/miniagents/dashboard_rollup.py`.
  3. `mark_decisions_surfaced` stamps `surfaced_in_brief_at` on the missed
     decisions we just listed, so they only appear in one brief.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Call,
    DashboardSnapshot,
    DecisionRequest,
    FieldEmployee,
    ManagerWorkspace,
)
from app.logging import get_logger

log = get_logger(__name__)


# ---------------- DTOs ----------------


@dataclass(frozen=True)
class MissedDecision:
    decision_id: str
    prompt: str
    call_id: str
    caller_name: str | None
    options: list[str]
    timed_out_at_iso: str


@dataclass(frozen=True)
class AccountMovement:
    slug: str
    title: str
    new_timeline_entries: int
    new_blockers: list[str]


@dataclass(frozen=True)
class RepActivity:
    field_employee_id: str
    name: str
    call_count: int
    top_topics: list[str]


@dataclass(frozen=True)
class StubEscalation:
    slug: str
    title: str
    mention_count: int


@dataclass(frozen=True)
class RollupAggregate:
    workspace_id: str
    workspace_name: str
    brief_date: date
    call_count: int
    top_topics: list[str]
    urgent_flags: list[str]
    missed_decisions: list[MissedDecision]
    account_movement: list[AccountMovement]
    reps_in_motion: list[RepActivity]
    stub_escalations: list[StubEscalation]


# ---------------- Compute ----------------


async def compute_aggregate(
    session: AsyncSession,
    workspace_id: UUID,
    brief_date: date,
) -> RollupAggregate:
    """Read-only - pulls every intermediate the brief needs in one pass."""

    ws_row = await session.get(ManagerWorkspace, workspace_id)
    workspace_name = ws_row.name if ws_row is not None else str(workspace_id)

    # 1. Call count - calls that ended on `brief_date` (UTC date bucket).
    call_count_result = await session.execute(
        text(
            "SELECT COUNT(*) FROM calls "
            "WHERE workspace_id = :wid "
            "AND DATE(started_at AT TIME ZONE 'UTC') = :sd "
            "AND status = 'ended'"
        ),
        {"wid": workspace_id, "sd": brief_date},
    )
    call_count = int(call_count_result.scalar_one() or 0)

    # 2. Missed decisions - timed_out and never surfaced before. We surface
    # them now; `mark_decisions_surfaced` (called by the mini-agent after the
    # brief is committed) stamps surfaced_in_brief_at so they appear only once.
    md_stmt = (
        select(DecisionRequest)
        .where(
            DecisionRequest.workspace_id == workspace_id,
            DecisionRequest.status == "timed_out",
            DecisionRequest.surfaced_in_brief_at.is_(None),
        )
        .order_by(DecisionRequest.responded_at.desc())
    )
    md_rows = list((await session.execute(md_stmt)).scalars().all())

    # Resolve caller_name (via Call.field_employee_id -> FieldEmployee.name).
    caller_name_by_call: dict[UUID, str | None] = {}
    if md_rows:
        call_ids = {d.call_id for d in md_rows}
        call_rows = list(
            (
                await session.execute(
                    select(Call.id, Call.field_employee_id).where(Call.id.in_(call_ids))
                )
            ).all()
        )
        fe_ids = {row.field_employee_id for row in call_rows if row.field_employee_id}
        fe_name_by_id: dict[UUID, str] = {}
        if fe_ids:
            fe_rows = list(
                (
                    await session.execute(
                        select(FieldEmployee.id, FieldEmployee.name).where(FieldEmployee.id.in_(fe_ids))
                    )
                ).all()
            )
            fe_name_by_id = {row.id: row.name for row in fe_rows}
        for row in call_rows:
            caller_name_by_call[row.id] = (
                fe_name_by_id.get(row.field_employee_id) if row.field_employee_id else None
            )

    missed_decisions = [
        MissedDecision(
            decision_id=str(d.id),
            prompt=d.prompt,
            call_id=str(d.call_id),
            caller_name=caller_name_by_call.get(d.call_id),
            options=list(d.options or []),
            timed_out_at_iso=(d.responded_at.isoformat() if d.responded_at else ""),
        )
        for d in md_rows
    ]

    # 3. Reps in motion - per-employee call counts on brief_date.
    reps_result = await session.execute(
        text(
            "SELECT fe.id AS fe_id, fe.name AS fe_name, COUNT(c.id) AS call_count "
            "FROM calls c JOIN field_employees fe ON fe.id = c.field_employee_id "
            "WHERE c.workspace_id = :wid "
            "AND DATE(c.started_at AT TIME ZONE 'UTC') = :sd "
            "AND c.status = 'ended' "
            "GROUP BY fe.id, fe.name "
            "ORDER BY call_count DESC, fe.name ASC"
        ),
        {"wid": workspace_id, "sd": brief_date},
    )
    reps_in_motion = [
        RepActivity(
            field_employee_id=str(row.fe_id),
            name=row.fe_name,
            call_count=int(row.call_count),
            # TODO: derive per-rep top topics from canonical_summary artifacts
            # once F4 brain integration is in place.
            top_topics=[],
        )
        for row in reps_result
    ]

    # 4-6. Placeholders - top_topics + account_movement + stub_escalations
    # depend on canonical_summary/brain reads that F4 wires up. The brief still
    # renders the section headers with "no activity" copy in the meantime.
    top_topics: list[str] = []  # TODO(F4): aggregate canonical_summary topics
    urgent_flags: list[str] = []  # TODO(F4): surface decision_timed_out + needs_review tags
    account_movement: list[AccountMovement] = []  # TODO(F4): scan brain timeline appends
    stub_escalations: list[StubEscalation] = []  # TODO(F4): brain stub->enriched promotion log

    return RollupAggregate(
        workspace_id=str(workspace_id),
        workspace_name=workspace_name,
        brief_date=brief_date,
        call_count=call_count,
        top_topics=top_topics,
        urgent_flags=urgent_flags,
        missed_decisions=missed_decisions,
        account_movement=account_movement,
        reps_in_motion=reps_in_motion,
        stub_escalations=stub_escalations,
    )


# ---------------- Write ----------------


async def write_snapshots(
    session: AsyncSession,
    agg: RollupAggregate,
    *,
    computed_at: datetime,
) -> int:
    """Materialise one row per dimension. Returns count written."""

    workspace_uuid = UUID(agg.workspace_id) if isinstance(agg.workspace_id, str) else agg.workspace_id
    rows: list[DashboardSnapshot] = []

    # overview: one row per (workspace, date)
    rows.append(
        DashboardSnapshot(
            workspace_id=workspace_uuid,
            snapshot_date=agg.brief_date,
            dimension="overview",
            key=None,
            metrics={
                "workspace_name": agg.workspace_name,
                "call_count": agg.call_count,
                "top_topics": list(agg.top_topics),
                "urgent_flags": list(agg.urgent_flags),
                "missed_decision_count": len(agg.missed_decisions),
                "reps_in_motion_count": len(agg.reps_in_motion),
                "account_movement_count": len(agg.account_movement),
                "stub_escalations_count": len(agg.stub_escalations),
            },
            computed_at=computed_at,
        )
    )

    # rep dim: one row per active rep on this date
    for rep in agg.reps_in_motion:
        rows.append(
            DashboardSnapshot(
                workspace_id=workspace_uuid,
                snapshot_date=agg.brief_date,
                dimension="rep",
                key=rep.field_employee_id,
                metrics={
                    "field_employee_id": rep.field_employee_id,
                    "name": rep.name,
                    "call_count": rep.call_count,
                    "top_topics": list(rep.top_topics),
                },
                computed_at=computed_at,
            )
        )

    # account dim: one row per moved account
    for acct in agg.account_movement:
        rows.append(
            DashboardSnapshot(
                workspace_id=workspace_uuid,
                snapshot_date=agg.brief_date,
                dimension="account",
                key=acct.slug,
                metrics={
                    "slug": acct.slug,
                    "title": acct.title,
                    "new_timeline_entries": acct.new_timeline_entries,
                    "new_blockers": list(acct.new_blockers),
                },
                computed_at=computed_at,
            )
        )

    # theme dim: one row per top topic
    for topic in agg.top_topics:
        rows.append(
            DashboardSnapshot(
                workspace_id=workspace_uuid,
                snapshot_date=agg.brief_date,
                dimension="theme",
                key=topic,
                metrics={"theme": topic, "mention_count": 0},
                computed_at=computed_at,
            )
        )

    # decision dim: one row per missed decision
    for md in agg.missed_decisions:
        rows.append(
            DashboardSnapshot(
                workspace_id=workspace_uuid,
                snapshot_date=agg.brief_date,
                dimension="decision",
                key=md.decision_id,
                metrics={
                    "decision_id": md.decision_id,
                    "call_id": md.call_id,
                    "prompt": md.prompt,
                    "options": list(md.options),
                    "caller_name": md.caller_name,
                    "timed_out_at_iso": md.timed_out_at_iso,
                    "status": "timed_out",
                },
                computed_at=computed_at,
            )
        )

    if not rows:
        return 0
    session.add_all(rows)
    await session.flush()
    return len(rows)


# ---------------- Stamp surfaced_in_brief_at ----------------


async def mark_decisions_surfaced(
    session: AsyncSession,
    decision_ids: list[UUID],
    *,
    at: datetime,
) -> int:
    """Set `surfaced_in_brief_at` on the listed decisions; idempotent."""
    if not decision_ids:
        return 0
    result = await session.execute(
        update(DecisionRequest)
        .where(
            DecisionRequest.id.in_(decision_ids),
            DecisionRequest.surfaced_in_brief_at.is_(None),
        )
        .values(surfaced_in_brief_at=at)
    )
    rowcount = getattr(result, "rowcount", 0) or 0
    return int(rowcount)
