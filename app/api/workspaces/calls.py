"""Calls REST endpoints - the minimum Phase 0 needs for the FE snapshot
and to verify the orchestrator end-to-end during dev.

Full call-detail surface (recordings, canonical summary, action items)
lands per LLD §D1 in Phase 1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Call
from app.db.repositories.calls_repo import CallsRepo
from app.db.repositories.manager_interventions_repo import ManagerInterventionsRepo
from app.db.repositories.transcripts_repo import TranscriptsRepo
from app.deps import CurrentUser, get_session, require_workspace_access
from app.errors import NotFound, VotFError
from app.realtime.bus import publish_frame
from app.realtime.redis_client import get_redis
from app.schemas.call import (
    CallListResponse,
    CallSummary,
    CallTranscriptResponse,
    TranscriptFragmentDTO,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/calls", tags=["calls"])


def _to_summary(c: Call) -> CallSummary:
    return CallSummary(
        id=c.id,
        workspace_id=c.workspace_id,
        field_employee_id=c.field_employee_id,
        agentphone_call_id=c.agentphone_call_id,
        from_number=c.from_number,
        to_number=c.to_number,
        status=c.status,
        started_at=c.started_at,
        ended_at=c.ended_at,
    )


@router.get(
    "",
    response_model=CallListResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def list_calls(
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CallListResponse:
    repo = CallsRepo(session)
    calls = await repo.list_for_workspace(workspace_id, status=status, limit=limit, offset=offset)
    return CallListResponse(
        calls=[_to_summary(c) for c in calls],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{call_id}",
    response_model=CallSummary,
    dependencies=[Depends(require_workspace_access)],
)
async def get_call(
    workspace_id: UUID,
    call_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CallSummary:
    repo = CallsRepo(session)
    call = await repo.get(call_id)
    if call is None or call.workspace_id != workspace_id:
        raise NotFound("call not found")
    return _to_summary(call)


@router.get(
    "/{call_id}/transcript",
    response_model=CallTranscriptResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def get_transcript(
    workspace_id: UUID,
    call_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CallTranscriptResponse:
    calls = CallsRepo(session)
    call = await calls.get(call_id)
    if call is None or call.workspace_id != workspace_id:
        raise NotFound("call not found")
    transcripts = TranscriptsRepo(session)
    fragments = await transcripts.list_for_call(call_id)
    return CallTranscriptResponse(
        call_id=call_id,
        fragments=[
            TranscriptFragmentDTO(id=f.id, seq=f.seq, speaker=f.speaker, text=f.text, ts=f.ts)
            for f in fragments
        ],
    )


@router.get(
    "/{call_id}/summary",
    dependencies=[Depends(require_workspace_access)],
)
async def get_call_summary(
    workspace_id: UUID,
    call_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """Returns the canonical summary for a call (§C11).

    Pulls the latest CallArtifact(kind=canonical_summary) for the call,
    fetches the blob from object storage, returns parsed content. Full
    call-detail surface (recordings, action items) lands per §D1.
    """
    import json as _json

    from app.db.repositories.call_artifacts_repo import CallArtifactsRepo
    from app.deps import get_object_store

    calls = CallsRepo(session)
    call = await calls.get(call_id)
    if call is None or call.workspace_id != workspace_id:
        raise NotFound("call not found")
    arts = CallArtifactsRepo(session)
    artifact = await arts.get_by_kind(call_id, "canonical_summary")
    if artifact is None:
        raise NotFound("summary not yet generated")
    storage = get_object_store()
    blob = await storage.get(artifact.storage_key)
    return dict(_json.loads(blob.decode("utf-8")))


# ---------------- Manager Intervention (whisper) - LLD §F7 ----------------

WHISPER_MAX_CHARS = 2000


class _WhisperTooLong(VotFError):
    http_status = 400
    code = "whisper_too_long"


class _CallEnded(VotFError):
    http_status = 409
    code = "call_ended"


def _whisper_redis_key(call_id: UUID) -> str:
    return f"whispers:{call_id}"


class WhisperRequest(BaseModel):
    guidance: str = Field(..., min_length=1)


class WhisperResponse(BaseModel):
    intervention_id: UUID


class ManagerInterventionDTO(BaseModel):
    id: UUID
    call_id: UUID
    workspace_id: UUID
    user_id: UUID
    mode: str
    started_at: datetime
    ended_at: datetime | None
    payload: dict[str, Any]


class InterventionListResponse(BaseModel):
    interventions: list[ManagerInterventionDTO]


@router.post(
    "/{call_id}/whisper",
    status_code=202,
    response_model=WhisperResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def whisper_to_call(
    workspace_id: UUID,
    call_id: UUID,
    body: WhisperRequest,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WhisperResponse:
    if len(body.guidance) > WHISPER_MAX_CHARS:
        raise _WhisperTooLong("whisper guidance exceeds 2000 chars")
    calls = CallsRepo(session)
    call = await calls.get(call_id)
    if call is None or call.workspace_id != workspace_id:
        raise NotFound("call not found")
    if call.status not in ("ringing", "in_progress"):
        raise _CallEnded("call has ended; whisper not accepted")

    now = datetime.now(UTC)
    repo = ManagerInterventionsRepo(session)
    row = await repo.create(
        call_id=call_id,
        workspace_id=workspace_id,
        user_id=user.id,
        mode="whisper",
        started_at=now,
        payload={"guidance": body.guidance, "consumed_at_turn": None},
    )
    await session.commit()

    # Push guidance onto a per-call Redis list; the turn loop drains via LRANGE+DEL.
    import json as _json

    r = get_redis()
    try:
        # RPUSH so LRANGE 0..-1 returns whispers in arrival order.
        await r.rpush(
            _whisper_redis_key(call_id),
            _json.dumps({"intervention_id": str(row.id), "guidance": body.guidance}),
        )
        # Bound TTL so abandoned calls don't leak keys; matches session TTL ballpark.
        await r.expire(_whisper_redis_key(call_id), 4 * 60 * 60 + 5 * 60)
    except Exception:
        # Best-effort; the row is the durable record.
        pass

    # Frame for FE confirmation that the whisper landed.
    await publish_frame(
        workspace_id,
        {
            "type": "manager_whisper",
            "call_id": str(call_id),
            "intervention_id": str(row.id),
            "guidance": body.guidance,
        },
    )

    return WhisperResponse(intervention_id=row.id)


# --- F1: recording + replay endpoints --------------------------------

@router.get(
    "/{call_id}/recording",
    dependencies=[Depends(require_workspace_access)],
)
async def get_recording(
    workspace_id: UUID,
    call_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """302 to a signed S3 URL (15 min TTL). 425 until AP delivers it."""
    from fastapi import HTTPException
    from fastapi.responses import RedirectResponse

    from app.deps import get_object_store

    calls = CallsRepo(session)
    call = await calls.get(call_id)
    if call is None or call.workspace_id != workspace_id:
        raise NotFound("call not found")
    if not call.recording_uri:
        raise HTTPException(status_code=425, detail="recording_not_ready_yet")
    store = get_object_store()
    url = await store.signed_url(call.recording_uri, ttl_seconds=900)
    return RedirectResponse(url=url, status_code=302)


@router.websocket("/{call_id}/replay")
async def replay_call(websocket, call_id: UUID):  # type: ignore[no-untyped-def]
    """WebSocket replay of historical transcript frames.

    Speed-variant: emits each TranscriptFragment in order with a fixed
    200ms gap. Original-cadence replay using ts deltas is follow-up.
    """
    import asyncio

    from app.db.app_session import app_session

    await websocket.accept()
    try:
        async with app_session() as session:
            t_repo = TranscriptsRepo(session)
            fragments = await t_repo.list_for_call(call_id)
        if not fragments:
            await websocket.send_json({"type": "replay_empty", "call_id": str(call_id)})
        else:
            for frag in fragments:
                await websocket.send_json({
                    "type": "transcript_fragment",
                    "speaker": frag.speaker,
                    "text": frag.text,
                    "ts": frag.ts.isoformat(),
                })
                await asyncio.sleep(0.2)
            await websocket.send_json({"type": "replay_done", "call_id": str(call_id)})
    finally:
        await websocket.close()


@router.get(
    "/{call_id}/interventions",
    response_model=InterventionListResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def list_interventions(
    workspace_id: UUID,
    call_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InterventionListResponse:
    calls = CallsRepo(session)
    call = await calls.get(call_id)
    if call is None or call.workspace_id != workspace_id:
        raise NotFound("call not found")
    repo = ManagerInterventionsRepo(session)
    rows = await repo.list_for_call(call_id)
    return InterventionListResponse(
        interventions=[
            ManagerInterventionDTO(
                id=r.id,
                call_id=r.call_id,
                workspace_id=r.workspace_id,
                user_id=r.user_id,
                mode=r.mode,
                started_at=r.started_at,
                ended_at=r.ended_at,
                payload=r.payload or {},
            )
            for r in rows
        ]
    )
