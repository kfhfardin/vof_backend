"""Decision timeout worker.

Per LLD §C7: when `DecisionService.open()` creates a row with a non-null
`timeout_at`, it schedules this job to fire at that time. The job:

  1. SELECT FOR UPDATE the row.
  2. If status != "open", noop (already answered or cancelled).
  3. Mark status=timed_out, responded_via=timeout, responded_at=now.
  4. Publish decision.resolved frame (response=null, via=timeout) so the FE
     drops the prompt.
  5. Append a SessionEvent("decision_timed_out", ...) on the call session
     so the next orchestrator turn knows to tell the Rep "Manager unavailable"
     and move on. The session event is consumed by app/orchestrator/prompts.py
     when it next renders.
  6. Do NOT enqueue brief flagging here - `surfaced_in_brief_at IS NULL`
     is the join column the Phase 1 §D5 brief generator uses; the row is
     already discoverable via `DecisionsRepo.list_for_workspace(status="timed_out")`.

Scheduling: `schedule_decision_timeout(decision_id, fire_at)` enqueues the
job via arq with a deferred dispatch time. The arq job_id is keyed
`dt:{decision_id}` so re-scheduling is idempotent (only one timeout per
decision can be in flight at a time).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from arq.connections import ArqRedis, RedisSettings, create_pool

from app.db.app_session import app_session
from app.db.repositories.decisions_repo import DecisionsRepo
from app.logging import get_logger
from app.realtime.bus import publish_frame
from app.schemas.ws_frames import DecisionResolvedFrame
from app.settings import get_settings


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


log = get_logger(__name__)


def job_id(decision_id: UUID) -> str:
    return f"dt:{decision_id}"


async def decision_timeout_job(ctx: dict[str, Any], decision_id_str: str) -> str:
    """Time-out a single decision. Returns the final status string."""
    decision_id = UUID(decision_id_str)
    async with app_session() as session:
        repo = DecisionsRepo(session)
        decision = await repo.lock_for_update(decision_id)
        if decision is None:
            log.warning("decision_timeout_row_missing", decision_id=decision_id_str)
            return "missing"
        if decision.status != "open":
            log.info(
                "decision_timeout_noop",
                decision_id=decision_id_str,
                status=decision.status,
            )
            return decision.status

        now = datetime.now(UTC)
        await repo.mark_timed_out(decision, ended_at=now)
        await session.commit()

        # Publish decision.resolved so the FE can drop the prompt.
        frame = DecisionResolvedFrame(
            call_id=decision.call_id,
            decision_id=decision.id,
            response=None,
            responded_via="timeout",
        ).model_dump(mode="json")
        await publish_frame(decision.workspace_id, frame)

        # Note: the orchestrator picks up timed-out decisions from
        # session.pending_decisions on the next turn and renders a
        # "Manager unavailable, moving on" cue. We don't push a separate
        # Redis event - the session render is the join.

        log.info("decision_timed_out", decision_id=decision_id_str)
        return "timed_out"


# ---------------- Scheduling helper ----------------


async def schedule_decision_timeout(decision_id: UUID, fire_at: datetime) -> None:
    """Enqueue the timeout job to fire at `fire_at`.

    Caller does this after committing the DecisionRequest row in
    DecisionService.open(). Idempotent: arq dedupes by `_job_id`, so a
    re-schedule for the same decision overwrites the prior deferred job.
    """
    pool = await create_pool(_redis_settings())
    try:
        await _enqueue_at(pool, fire_at, decision_id)
    finally:
        await pool.close()


async def _enqueue_at(pool: ArqRedis, fire_at: datetime, decision_id: UUID) -> None:
    # arq uses defer_until or defer_by; defer_until takes a datetime in UTC.
    if fire_at.tzinfo is None:
        fire_at = fire_at.replace(tzinfo=UTC)
    await pool.enqueue_job(
        "decision_timeout_job",
        str(decision_id),
        _job_id=job_id(decision_id),
        _defer_until=fire_at,
    )


# ---------------- Test/dev hook ----------------


def _is_test_mode() -> bool:
    """True if we should run timeouts inline instead of scheduling on Redis.

    Useful for tests that don't want to bring up an arq worker just to fire
    one job. Toggled via the DECISION_TIMEOUT_INLINE env var (any non-empty
    value).
    """
    import os

    return bool(os.environ.get("DECISION_TIMEOUT_INLINE"))


async def schedule_or_inline(decision_id: UUID, fire_at: datetime) -> None:
    """Used by DecisionService.open(). Routes to arq enqueue normally, or
    skips entirely in test mode (the test fires the job manually).
    """
    if _is_test_mode():
        return
    _settings = get_settings()
    await schedule_decision_timeout(decision_id, fire_at)
