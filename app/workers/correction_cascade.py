"""Correction cascade worker.

Per LLD §C8 / HLD §9.4. Phase 0 minimum:

  - Log the correction so ops + audit dashboards see it.
  - Reserve hooks for the heavier propagation (denormalized caller
    `owned_accounts` updates, retrieval-cache invalidation, embedding
    recompute). The hooks are TODO comments not stubs - the next
    section that owns each piece flips them on:

      - caller_profiles denorm  -> §C11 wires it once CallerBrainHandler
        does real writes
      - retrieval cache invalidation -> §D3 has the cache layer
      - embedding recompute -> §D3 has the embeddings

Idempotent by (workspace_id, slug, kind) for safety - re-running has no
extra effect because the brain page version chain is the source of truth.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from arq.connections import ArqRedis, create_pool

from app.logging import get_logger
from app.workers.decision_timeout import _redis_settings

log = get_logger(__name__)


def job_id(workspace_id: UUID, slug: str, kind: str) -> str:
    return f"cc:{workspace_id}:{slug}:{kind}"


async def correction_cascade_job(
    ctx: dict[str, Any],
    workspace_id_str: str,
    slug: str,
    kind: str,
) -> str:
    workspace_id = UUID(workspace_id_str)
    log.info(
        "correction_cascade_run",
        workspace_id=str(workspace_id),
        slug=slug,
        kind=kind,
    )
    # TODO (§C11): caller_profiles denorm
    # TODO (§D3):  retrieval-cache invalidation
    # TODO (§D3):  embedding recompute
    return "ok"


def _is_inline_mode() -> bool:
    import os

    return bool(os.environ.get("CORRECTION_CASCADE_INLINE"))


async def schedule_or_inline(*, workspace_id: UUID, slug: str, kind: str) -> None:
    """Routes to arq under normal operation; skips in test mode."""
    if _is_inline_mode():
        return
    pool = await create_pool(_redis_settings())
    try:
        await _enqueue(pool, workspace_id=workspace_id, slug=slug, kind=kind)
    finally:
        await pool.close()


async def _enqueue(pool: ArqRedis, *, workspace_id: UUID, slug: str, kind: str) -> None:
    await pool.enqueue_job(
        "correction_cascade_job",
        str(workspace_id),
        slug,
        kind,
        _job_id=job_id(workspace_id, slug, kind),
    )
