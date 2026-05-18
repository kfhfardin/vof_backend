"""AgentPhone webhook endpoint.

Sequence (LLD §C3):

  1. Read raw body + headers.
  2. HMAC verify (constant time) using AGENTPHONE_WEBHOOK_SECRET.
  3. Replay-window check (reject deliveries older than 5 minutes).
  4. Dedupe by X-Webhook-ID (Redis SETNX with 7-day TTL).
  5. Adapter.parse_webhook -> TelephonyEvent.
  6. Resolve scope + materialize Call/FieldEmployee rows.
  7. Dispatch to the right handler:
       voice_turn -> NDJSON StreamingResponse
       sms        -> 200 (handler runs sync, returns OK)
       call_ended -> 200 (handler enqueues post_call worker; §C11)
       reaction   -> 200 (no-op in Phase 0)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, get_telephony_provider
from app.errors import NotFound
from app.logging import get_logger
from app.realtime.bus import publish_frame
from app.realtime.redis_client import claim_webhook_id
from app.security.hmac import (
    ReplayWindowExceeded,
    verify_agentphone_webhook,
)
from app.settings import get_settings
from app.telephony.base import TelephonyProvider
from app.telephony.dispatcher import get_dispatcher, materialize_scope_and_call
from app.telephony.events import (
    CallEnded,
    InboundSMS,
    InboundVoiceTurn,
    ReactionReceived,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = get_logger(__name__)


@router.post("/agentphone")
async def agentphone_webhook(
    request: Request,
    adapter: Annotated[TelephonyProvider, Depends(get_telephony_provider)],
    session: Annotated[AsyncSession, Depends(get_session)],
    x_webhook_signature: Annotated[str | None, Header()] = None,
    x_webhook_timestamp: Annotated[str | None, Header()] = None,
    x_webhook_id: Annotated[str | None, Header()] = None,
    x_webhook_event: Annotated[str | None, Header()] = None,
) -> Response:
    raw_body = await request.body()
    settings = get_settings()
    secret = settings.agentphone_webhook_secret.get_secret_value()

    # 1-2-3. HMAC + replay window
    if not x_webhook_signature or not x_webhook_timestamp:
        return Response(status_code=401, content="missing signature headers")
    try:
        ok = verify_agentphone_webhook(
            raw_body,
            x_webhook_signature,
            x_webhook_timestamp,
            secret,
        )
    except ReplayWindowExceeded as e:
        log.warning("webhook_replay_window_exceeded", detail=str(e))
        return Response(status_code=400, content="replay window exceeded")
    if not ok:
        log.warning("webhook_hmac_mismatch", header=x_webhook_signature[:32])
        return Response(status_code=401, content="bad signature")

    # 4. Dedupe by X-Webhook-ID
    if x_webhook_id:
        claimed = await claim_webhook_id(x_webhook_id)
        if not claimed:
            # Already processed - return 200 quickly so AP stops retrying.
            return Response(status_code=200)

    # 5. Parse the event
    headers = dict(request.headers)
    try:
        event = adapter.parse_webhook(raw_body, headers)
    except Exception as e:
        log.exception("webhook_parse_failed", header_event=x_webhook_event)
        return Response(status_code=400, content=f"parse failed: {e}")

    # 6. Resolve scope + ensure Call/FE rows exist
    try:
        materialized = await materialize_scope_and_call(session, event)
    except NotFound as e:
        log.warning("webhook_unknown_scope", detail=str(e))
        await session.rollback()
        return Response(status_code=404, content=str(e))
    await session.commit()

    # 7. Publish lifecycle frames (call.started / call.ended) to the WS bus.
    for frame in materialized.pending_frames:
        await publish_frame(materialized.workspace_id, frame)

    # 8. Dispatch
    dispatcher = get_dispatcher()
    call_id = materialized.call_id
    if isinstance(event, InboundVoiceTurn):
        assert call_id is not None  # materialize creates one for voice turns
        gen = dispatcher.voice.handle(event, call_id=call_id)
        return StreamingResponse(gen, media_type="application/x-ndjson")
    if isinstance(event, InboundSMS):
        await dispatcher.sms.handle(event, workspace_id=materialized.workspace_id)
        return Response(status_code=200)
    if isinstance(event, CallEnded):
        assert call_id is not None
        await dispatcher.call_ended.handle(event, call_id=call_id)
        return Response(status_code=200)
    if isinstance(event, ReactionReceived):
        return Response(status_code=200)
    return Response(status_code=200)
