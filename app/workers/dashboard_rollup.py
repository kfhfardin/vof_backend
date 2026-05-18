"""Daily dashboard rollup worker (LLD §F8).

Two arq jobs:

  - `dashboard_rollup_job(workspace_id, brief_date)` does the actual work
    for one workspace. Idempotent via job_id `db:{workspace_id}:{date}` so a
    re-trigger for the same date overwrites the prior deferred job rather
    than producing two briefs.

  - `dashboard_rollup_dispatcher_job` is the once-daily cron entry. It
    selects every workspace and enqueues a `dashboard_rollup_job` per
    workspace for yesterday's UTC date. Splitting the cron from the
    per-workspace job keeps each invocation bounded and isolates failures.

The cron is registered via `arq.cron.cron` in `app/workers/settings.py` to
fire at 07:00 UTC daily.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from arq.connections import ArqRedis, create_pool
from sqlalchemy import select

from app.db.app_session import app_session
from app.db.models import ManagerWorkspace
from app.logging import get_logger
from app.miniagents.dashboard_rollup import (
    DashboardRollupInput,
    run_dashboard_rollup,
)
from app.workers.decision_timeout import _redis_settings

log = get_logger(__name__)


def per_workspace_job_id(workspace_id: UUID, brief_date: date) -> str:
    return f"db:{workspace_id}:{brief_date.isoformat()}"


# ---------------- Per-workspace job ----------------


async def dashboard_rollup_job(
    ctx: dict[str, Any],
    workspace_id_str: str,
    brief_date_str: str,
) -> str:
    """Run the rollup for one workspace + date. Returns brief_id on success."""
    workspace_id = UUID(workspace_id_str)
    brief_date = date.fromisoformat(brief_date_str)
    try:
        result = await run_dashboard_rollup(
            DashboardRollupInput(workspace_id=workspace_id, brief_date=brief_date)
        )
    except Exception:
        log.exception(
            "dashboard_rollup_job_failed",
            workspace_id=workspace_id_str,
            brief_date=brief_date_str,
        )
        raise
    log.info(
        "dashboard_rollup_job_complete",
        workspace_id=workspace_id_str,
        brief_date=brief_date_str,
        brief_id=str(result.brief_artifact_id),
        snapshots_written=result.snapshots_written,
    )
    return str(result.brief_artifact_id)


# ---------------- Dispatcher cron ----------------


async def dashboard_rollup_dispatcher_job(ctx: dict[str, Any]) -> int:
    """Enumerate workspaces; enqueue one per-workspace rollup for yesterday."""
    brief_date = (datetime.now(UTC) - timedelta(days=1)).date()
    pool: ArqRedis = ctx.get("redis")  # arq injects the pool in cron ctx
    if pool is None:
        pool = await create_pool(_redis_settings())
        close_pool = True
    else:
        close_pool = False

    try:
        async with app_session() as session:
            result = await session.execute(select(ManagerWorkspace.id))
            workspace_ids = [row[0] for row in result.all()]

        enqueued = 0
        for wid in workspace_ids:
            try:
                await _enqueue_per_workspace(pool, wid, brief_date)
                enqueued += 1
            except Exception:
                log.exception(
                    "dashboard_rollup_dispatch_enqueue_failed",
                    workspace_id=str(wid),
                    brief_date=brief_date.isoformat(),
                )
        log.info(
            "dashboard_rollup_dispatcher_complete",
            brief_date=brief_date.isoformat(),
            enqueued=enqueued,
            total=len(workspace_ids),
        )
        return enqueued
    finally:
        if close_pool:
            await pool.close()


async def _enqueue_per_workspace(
    pool: ArqRedis,
    workspace_id: UUID,
    brief_date: date,
) -> None:
    await pool.enqueue_job(
        "dashboard_rollup_job",
        str(workspace_id),
        brief_date.isoformat(),
        _job_id=per_workspace_job_id(workspace_id, brief_date),
    )


# ---------------- Test/dev hook ----------------


def _is_inline_mode() -> bool:
    import os

    return bool(os.environ.get("DASHBOARD_ROLLUP_INLINE"))


async def schedule_or_inline(workspace_id: UUID, brief_date: date) -> None:
    """Routes to arq normally; runs inline in test mode."""
    if _is_inline_mode():
        await dashboard_rollup_job({}, str(workspace_id), brief_date.isoformat())
        return
    pool = await create_pool(_redis_settings())
    try:
        await _enqueue_per_workspace(pool, workspace_id, brief_date)
    finally:
        await pool.close()
