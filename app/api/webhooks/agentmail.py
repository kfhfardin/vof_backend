"""AgentMail webhook endpoint (Phase 1 §F6).

Unauthenticated; no HMAC/Svix verification (speed variant). Parses the
raw body, dispatches into email_reply_handler, always returns 200 so
AgentMail stops retrying — handler-side failures get logged but don't
become webhook retries (the email_messages.correlation_idempotency_key
unique constraint protects the outbound side; inbound duplicates would
just create a second IntakeBufferItem, which the Manager can dismiss).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.email.agentmail import AgentMailEmailProvider
from app.logging import get_logger
from app.miniagents.email_reply_handler import handle_event

router = APIRouter(prefix="/integrations", tags=["webhooks"])
log = get_logger(__name__)


@router.post("/agentmail/webhook")
async def agentmail_webhook(request: Request) -> Response:
    raw = await request.body()
    provider = AgentMailEmailProvider()
    event = provider.parse_webhook(raw_body=raw)
    if event is None:
        return Response(status_code=200)
    try:
        await handle_event(event)
    except Exception:
        log.exception("agentmail_reply_handler_failed")
    return Response(status_code=200)
