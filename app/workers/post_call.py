"""post_call worker - the §C11 fan-out that runs after every call.

Sequence (LLD §C11):

  1. Load call + assemble transcript.
  2. Run summarizer skill -> SummarizerOutput.
  3. Save summary as a CallArtifact (JSON in object storage).
  4. PARALLEL: brain_updater + caller_memory_write.
  5. Publish call.summary_ready WS frame.

Independent failure domains: a brain_updater failure does NOT roll back
the summary; a caller_memory_write failure does NOT roll back either.
The frame's `has_summary` flag tells the FE whether the canonical summary
landed; brain side errors are recoverable via re-run.

Idempotent by stable arq job_id post_call:{call_id} - re-runs are safe
because summary upserts are blob writes (overwrite-by-key) and brain
upserts skip same-content cases.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from arq.connections import ArqRedis, create_pool

from app.db.app_session import app_session
from app.db.repositories.call_artifacts_repo import CallArtifactsRepo
from app.db.repositories.calls_repo import CallsRepo
from app.db.repositories.field_employees_repo import FieldEmployeesRepo
from app.db.repositories.transcripts_repo import TranscriptsRepo
from app.deps import get_brain_provider, get_memory_provider, get_object_store
from app.logging import get_logger
from app.miniagents.brain_updater import BrainUpdateInput, run_brain_updater
from app.miniagents.caller_memory_writer import write_call_to_caller_memory
from app.miniagents.summarizer_agent import SummarizerInput, run_summarizer
from app.realtime.bus import publish_frame
from app.schemas.ws_frames import CallSummaryReadyFrame
from app.storage.base import workspace_key
from app.workers.decision_timeout import _redis_settings

log = get_logger(__name__)


def job_id(call_id: UUID) -> str:
    return f"post_call:{call_id}"


def _summary_storage_key(workspace_id: UUID, call_id: UUID) -> str:
    return workspace_key(workspace_id, "calls", str(call_id), "canonical_summary.json")


async def post_call_job(ctx: dict[str, Any], call_id_str: str) -> str:
    """Fan-out entry point. Returns a terse status string for the worker log."""
    call_id = UUID(call_id_str)
    storage = get_object_store()
    brain = get_brain_provider()
    memory = get_memory_provider()

    # 1. Load call + transcript + caller.
    async with app_session() as session:
        calls = CallsRepo(session)
        transcripts = TranscriptsRepo(session)
        fes = FieldEmployeesRepo(session)
        call = await calls.get(call_id)
        if call is None:
            log.warning("post_call_call_missing", call_id=call_id_str)
            return "missing"
        if call.status != "ended":
            log.warning(
                "post_call_skip_non_ended",
                call_id=call_id_str,
                status=call.status,
            )
            return "skipped"
        fragments = await transcripts.list_for_call(call_id)
        field_employee = await fes.get(call.field_employee_id) if call.field_employee_id else None

    if not fragments:
        log.warning("post_call_no_transcript", call_id=call_id_str)
        # Still publish the frame so the FE doesn't hang waiting for it.
        await _publish_ready(call.workspace_id, call_id, has_summary=False, brain_pages=[])
        return "no_transcript"

    provider_summary_text: str | None = None
    if call.provider_summary and isinstance(call.provider_summary, dict):
        provider_summary_text = call.provider_summary.get("summary")

    # 2. Summarize.
    summary_input = SummarizerInput(
        call=call,
        caller_name=field_employee.name if field_employee else None,
        caller_role=field_employee.role if field_employee else None,
        transcript=fragments,
        provider_summary_text=provider_summary_text,
        brain_context=[],  # §D3 will populate from hybrid_search at call-end time
    )
    summary = await run_summarizer(summary_input)

    # 3. Save canonical summary artifact (object storage + DB row).
    artifact_payload = {
        "call_id": str(call.id),
        "workspace_id": str(call.workspace_id),
        "ended_at": call.ended_at.isoformat() if call.ended_at else None,
        "summary": summary.to_dict(),
        "transcript_turn_count": len(fragments),
    }
    blob = json.dumps(artifact_payload, indent=2).encode("utf-8")
    key = _summary_storage_key(call.workspace_id, call.id)
    try:
        await storage.put(key, blob, "application/json")
        sha = hashlib.sha256(blob).hexdigest()
        async with app_session() as session2:
            arts = CallArtifactsRepo(session2)
            await arts.create(
                call_id=call.id,
                workspace_id=call.workspace_id,
                kind="canonical_summary",
                storage_key=key,
                bytes_=len(blob),
                content_type="application/json",
                sha256=sha,
            )
            await session2.commit()
    except Exception:
        log.exception("post_call_summary_save_failed", call_id=call_id_str)

    # 4. PARALLEL fan-out: brain_updater + caller_memory_writer + web_verifier
    # + action_item heuristic extraction. Each in its own session/task;
    # failures isolated per LLD §F2.
    import asyncio

    from app.miniagents.web_verifier import web_verifier_fanout
    from app.services.action_items.heuristic_extractor import (
        extract_action_item_candidates,
    )
    from app.services.action_items.save import save_action_items

    # Heuristic action-item extraction is sync/cheap; do it inline.
    # TranscriptFragment duck-types to TranscriptTurnView (speaker, text).
    action_items = extract_action_item_candidates(
        blockers=summary.blockers,
        transcript_turns=fragments,  # type: ignore[arg-type]
    )

    # Claim extraction is not shipped in this phase — pass [] to verifier_fanout.
    # Infrastructure is in place for when a claim extractor (skill or heuristic)
    # is added later. TODO: heuristic or LLM-based claim extraction.
    verifier_claims: list = []

    brain_task = asyncio.create_task(
        run_brain_updater(
            BrainUpdateInput(workspace_id=call.workspace_id, call_id=call.id, summary=summary),
            brain=brain,
        )
    )
    memory_task = asyncio.create_task(
        write_call_to_caller_memory(
            call=call,
            field_employee=field_employee,
            transcript=fragments,
            summary=summary,
            memory=memory,
        )
    )
    verifier_task = asyncio.create_task(
        web_verifier_fanout(
            workspace_id=call.workspace_id,
            call_id=call.id,
            claims=verifier_claims,
        )
    )
    brain_result, memory_result, verifier_result = await asyncio.gather(
        brain_task, memory_task, verifier_task, return_exceptions=True
    )

    brain_pages_touched: list[str] = []
    if isinstance(brain_result, BaseException):
        log.error("post_call_brain_failed", call_id=call_id_str, error=str(brain_result))
    else:
        brain_pages_touched = list(brain_result.pages_upserted) + list(brain_result.timeline_appends)
    if isinstance(memory_result, BaseException):
        log.error("post_call_memory_failed", call_id=call_id_str, error=str(memory_result))
    if isinstance(verifier_result, BaseException):
        log.error("post_call_verifier_failed", call_id=call_id_str, error=str(verifier_result))

    # Persist action items (best-effort).
    if action_items:
        try:
            async with app_session() as session3:
                await save_action_items(session3, call=call, candidates=action_items)
                await session3.commit()
        except Exception:
            log.exception("post_call_action_items_save_failed", call_id=call_id_str)

    # 5. Publish the WS frame so the FE re-fetches the summary.
    await _publish_ready(call.workspace_id, call_id, has_summary=True, brain_pages=brain_pages_touched)

    # 6. F6 email fan-out — enqueue per opted-in recipient. Best-effort.
    try:
        await _enqueue_post_call_emails(call, field_employee)
    except Exception:
        log.exception("post_call_email_fanout_failed", call_id=call_id_str)

    log.info(
        "post_call_complete",
        call_id=call_id_str,
        brain_pages_touched=len(brain_pages_touched),
        action_items_extracted=len(action_items),
        memory_written=getattr(memory_result, "written", False),
    )
    return "ok"


async def _enqueue_post_call_emails(call, field_employee) -> None:
    """Enqueue email_delivery jobs for opted-in Manager / Rep recipients."""
    from arq.connections import create_pool

    from app.db.app_session import app_session
    from app.db.repositories.workspaces_repo import WorkspacesRepo

    async with app_session() as session:
        ws_repo = WorkspacesRepo(session)
        workspace = await ws_repo.get_by_id(call.workspace_id)
        manager_email = None
        if workspace is not None:
            manager_email = await ws_repo.get_manager_email(call.workspace_id)
    if workspace is None:
        return
    email_cfg = (workspace.config or {}).get("email", {})
    if not email_cfg.get("enabled"):
        return

    pool = await create_pool(_redis_settings())
    try:
        if email_cfg.get("manager_post_call_summary") and manager_email:
            await pool.enqueue_job(
                "email_delivery_job",
                {
                    "workspace_id": str(call.workspace_id),
                    "trigger_kind": "post_call_summary",
                    "trigger_ref_id": str(call.id),
                    "recipient_class": "manager",
                    "recipient_addr": manager_email,
                },
            )
        if email_cfg.get("rep_post_call_summary") and field_employee is not None:
            rep_email = getattr(field_employee, "email", None) or (
                getattr(field_employee, "profile", {}) or {}
            ).get("email")
            if rep_email:
                await pool.enqueue_job(
                    "email_delivery_job",
                    {
                        "workspace_id": str(call.workspace_id),
                        "trigger_kind": "post_call_summary",
                        "trigger_ref_id": str(call.id),
                        "recipient_class": "rep",
                        "recipient_addr": rep_email,
                    },
                )
    finally:
        await pool.close()


async def _publish_ready(
    workspace_id: UUID,
    call_id: UUID,
    *,
    has_summary: bool,
    brain_pages: list[str],
) -> None:
    frame = CallSummaryReadyFrame(
        call_id=call_id,
        has_summary=has_summary,
        brain_pages_touched=brain_pages,
    ).model_dump(mode="json")
    await publish_frame(workspace_id, frame)


# ---------------- Scheduling helper ----------------


def _is_inline_mode() -> bool:
    import os

    return bool(os.environ.get("POST_CALL_INLINE"))


async def schedule_or_inline(call_id: UUID) -> None:
    """Routes to arq under normal operation; runs inline in test mode."""
    if _is_inline_mode():
        await post_call_job({}, str(call_id))
        return
    pool = await create_pool(_redis_settings())
    try:
        await _enqueue(pool, call_id)
    finally:
        await pool.close()


async def _enqueue(pool: ArqRedis, call_id: UUID) -> None:
    await pool.enqueue_job(
        "post_call_job",
        str(call_id),
        _job_id=job_id(call_id),
    )
