"""Webhook dispatcher - the seam between the AgentPhone endpoint and
the consumers of each event type.

For Phase 0 §C3, the default handlers persist the inbound state (Call rows,
provider_summary on call.ended) and produce a minimal NDJSON reply for voice
turns. §C4 will register a richer voice handler that delegates to the
Orchestrator turn loop; §C11 will register a richer call.ended handler that
enqueues post-call writeback.

The seam lets §C3 ship a working end-to-end webhook without bolting on
half-built orchestrator code.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.calls_repo import CallsRepo
from app.db.repositories.field_employees_repo import FieldEmployeesRepo
from app.db.repositories.workspaces_repo import WorkspacesRepo
from app.errors import NotFound
from app.logging import get_logger
from app.telephony.events import (
    CallEnded,
    InboundSMS,
    InboundVoiceTurn,
    TelephonyEvent,
)

log = get_logger(__name__)


class VoiceTurnHandler(Protocol):
    def handle(self, event: InboundVoiceTurn, *, call_id: UUID) -> AsyncIterator[bytes]:
        """Return an async iterator of NDJSON byte chunks to send back to AgentPhone.

        Implementations are typically wrappers around an `async def ... yield ...`
        generator function so the returned object is an AsyncIterator (not an
        awaitable returning an AsyncIterator).
        """


class SMSHandler(Protocol):
    async def handle(self, event: InboundSMS, *, workspace_id: UUID) -> None:
        """Handle an inbound SMS. `workspace_id` is the resolved workspace
        from `materialize_scope_and_call` — passed explicitly because the
        webhook adapter can't mutate the frozen InboundSMS event after the
        dispatcher resolves scope via the to_number/numberId/agentId fallback."""


class CallEndedHandler(Protocol):
    async def handle(self, event: CallEnded, *, call_id: UUID) -> None: ...


# ---------------- Default Phase 0 handlers ----------------


class _Phase0VoiceTurnHandler:
    """Minimal NDJSON producer until §C4 orchestrator is wired.

    Emits one final chunk acknowledging the turn so AgentPhone's TTS plays
    something; logs the transcript. The orchestrator (§C4) will register
    a real handler that streams from the LLM.
    """

    def handle(self, event: InboundVoiceTurn, *, call_id: UUID) -> AsyncIterator[bytes]:
        return self._stream(event, call_id)

    async def _stream(self, event: InboundVoiceTurn, call_id: UUID) -> AsyncIterator[bytes]:
        log.info(
            "voice_turn_phase0_default",
            call_id=str(call_id),
            transcript_preview=event.transcript[:120],
        )
        reply = {"text": "Got it. I'm still being set up - I'll capture this for review."}
        yield (json.dumps(reply) + "\n").encode("utf-8")


class _Phase0SMSHandler:
    """Inbound SMS handler.

    First-match resolution:
      1. If body starts with `[DR-XXXXXX]` and the sender is a Workspace's
         Manager with an open decision matching that short id, treat as
         the Manager's response to that decision (§C6).
      2. Otherwise, log + drop. The brain-write path ("note: customer X
         said Y" -> new brain page) is §C8 territory.
    """

    async def handle(self, event: InboundSMS, *, workspace_id: UUID) -> None:
        from app.db.app_session import app_session
        from app.db.repositories.workspaces_repo import WorkspacesRepo
        from app.services.decisions import DecisionService

        if not event.body.strip().startswith("[DR-"):
            log.info(
                "inbound_sms_phase0_default",
                channel=event.channel,
                from_number=event.from_number,
                workspace_id=str(workspace_id),
                body_preview=event.body[:120],
            )
            return

        async with app_session() as session:
            workspaces = WorkspacesRepo(session)
            ws = await workspaces.get_by_id(workspace_id)
            if ws is None or ws.manager_user_id is None:
                log.warning(
                    "inbound_sms_dr_no_manager",
                    workspace_id=str(workspace_id),
                )
                return
            svc = DecisionService(session)
            matched = await svc.match_sms_response(
                body=event.body,
                manager_user_id=ws.manager_user_id,
            )
            if matched is None:
                log.info(
                    "inbound_sms_dr_no_match",
                    body_preview=event.body[:120],
                )


class _Phase0CallEndedHandler:
    """Enqueue post_call (§C11). Survives a Redis blip via the inline-mode
    toggle so dev environments without arq still process the writeback.
    """

    async def handle(self, event: CallEnded, *, call_id: UUID) -> None:
        from app.workers.post_call import schedule_or_inline

        log.info(
            "call_ended_dispatch_post_call",
            call_id=str(call_id),
            ap_call_id=event.ap_call_id,
            transcript_len=len(event.full_transcript),
        )
        try:
            await schedule_or_inline(call_id)
        except Exception:
            log.exception("post_call_enqueue_failed", call_id=str(call_id))


# ---------------- Registry ----------------


class WebhookDispatcher:
    """Per-process registry of handlers. Defaults are Phase 0; §C4/§C11
    swap them via set_voice_handler / set_call_ended_handler.
    """

    def __init__(self) -> None:
        self.voice: VoiceTurnHandler = _Phase0VoiceTurnHandler()
        self.sms: SMSHandler = _Phase0SMSHandler()
        self.call_ended: CallEndedHandler = _Phase0CallEndedHandler()

    def set_voice_handler(self, handler: VoiceTurnHandler) -> None:
        self.voice = handler

    def set_sms_handler(self, handler: SMSHandler) -> None:
        self.sms = handler

    def set_call_ended_handler(self, handler: CallEndedHandler) -> None:
        self.call_ended = handler


_dispatcher = WebhookDispatcher()


def get_dispatcher() -> WebhookDispatcher:
    return _dispatcher


# ---------------- Scope + Call materialization ----------------


@dataclass
class MaterializeResult:
    workspace_id: UUID
    call_id: UUID | None
    # Frames to publish to the multi-call WS bus AFTER session.commit().
    # Empty for events that don't change call lifecycle.
    pending_frames: list[dict[str, Any]] = field(default_factory=list)


async def materialize_scope_and_call(
    session: AsyncSession,
    event: TelephonyEvent,
) -> MaterializeResult:
    """Resolve workspace_id and ensure a Call row exists.

    Returns a MaterializeResult carrying (a) the workspace + call ids and
    (b) any lifecycle frames the caller should publish after commit. The
    webhook endpoint commits the session, then iterates pending_frames and
    publishes each.

    Scope resolution policy (per LLD §C3):
      1. Use scope.workspace_id from conversationState echo, if present.
      2. Fall back to ManagerWorkspace.where(primary_number=event.to_number).
    """
    from app.schemas.ws_frames import CallEndedFrame, CallStartedFrame

    workspaces = WorkspacesRepo(session)
    calls = CallsRepo(session)
    fes = FieldEmployeesRepo(session)

    # AP delivers live voice turns with data.to / data.from / data.callId
    # often empty — only data.numberId and the top-level agentId are reliable.
    # Resolve scope by falling through every available identifier.
    to_number = event.to_number if isinstance(event, InboundVoiceTurn | InboundSMS | CallEnded) else None
    ap_number_id = event.ap_number_id if isinstance(event, InboundVoiceTurn | CallEnded) else ""
    ap_agent_id = event.ap_agent_id if isinstance(event, InboundVoiceTurn | CallEnded) else ""

    workspace_id: UUID | None = None
    resolved_via = "unresolved"
    if event.scope and event.scope.workspace_id and event.scope.workspace_id.int != 0:
        workspace_id = event.scope.workspace_id
        resolved_via = "conversation_state"
    elif to_number:
        ws = await workspaces.get_by_primary_number(to_number)
        if ws is not None:
            workspace_id = ws.id
            resolved_via = "primary_number"
    if workspace_id is None and ap_number_id:
        ws = await workspaces.get_by_agentphone_number_id(ap_number_id)
        if ws is not None:
            workspace_id = ws.id
            resolved_via = "agentphone_number_id"
    if workspace_id is None and ap_agent_id:
        ws = await workspaces.get_by_agentphone_agent_id(ap_agent_id)
        if ws is not None:
            workspace_id = ws.id
            resolved_via = "agentphone_agent_id"

    if workspace_id is None:
        if isinstance(event, CallEnded) and event.ap_call_id:
            call = await calls.get_by_agentphone_id(event.ap_call_id)
            if call is not None:
                return MaterializeResult(workspace_id=call.workspace_id, call_id=call.id, pending_frames=[])
        raise NotFound(
            f"unknown_number (tried primary_number={to_number!r} "
            f"number_id={ap_number_id!r} agent_id={ap_agent_id!r})"
        )
    log.info("webhook_scope_resolved", workspace_id=str(workspace_id), via=resolved_via)

    ws = await workspaces.get_by_id(workspace_id)
    if ws is None:
        raise NotFound("workspace_vanished")

    if isinstance(event, InboundVoiceTurn):
        existing = await calls.get_by_agentphone_id(event.ap_call_id) if event.ap_call_id else None
        if existing is None and not event.ap_call_id:
            # AP voice turns commonly arrive with callId=null. Attach to the
            # most-recent in-progress call for this workspace (started within
            # the last 20 minutes — long enough for any real call, short
            # enough not to bleed across sessions). When call.ended arrives
            # with the real callId, we stamp it onto this row then.
            from datetime import UTC, datetime, timedelta

            in_progress = await calls.list_in_progress(workspace_id)
            cutoff = datetime.now(UTC) - timedelta(minutes=20)
            for c in in_progress:
                started = c.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
                if started >= cutoff:
                    existing = c
                    break
        if existing is not None:
            return MaterializeResult(workspace_id=workspace_id, call_id=existing.id, pending_frames=[])

        field_employee_id: UUID | None = (
            event.scope.field_employee_id if event.scope and event.scope.field_employee_id else None
        )
        if field_employee_id is None and event.from_number:
            fe = await fes.find_by_phone(workspace_id, event.from_number)
            if fe is None:
                fe = await fes.create_unprofiled(
                    workspace_id=workspace_id,
                    organization_id=ws.organization_id,
                    phone=event.from_number,
                )
            field_employee_id = fe.id

        from datetime import UTC, datetime

        started_at = event.delivery_timestamp or datetime.now(UTC)
        # Synthesize a placeholder ap_call_id when AP omits it. Key shape:
        #   ap_<numberId>_<unix_ts>
        # numberId is the only stable identifier AP gives us on live voice
        # turns; the timestamp suffix separates back-to-back calls on the
        # same line. On call.ended (which DOES carry the real AP callId),
        # the CallEnded branch below rewrites this field to the real id.
        synthetic_ap_call_id = event.ap_call_id or (
            f"ap_{event.ap_number_id or workspace_id}_{int(started_at.timestamp())}"
        )
        call = await calls.create(
            workspace_id=workspace_id,
            organization_id=ws.organization_id,
            agentphone_call_id=synthetic_ap_call_id,
            from_number=event.from_number or None,
            to_number=event.to_number or None,
            started_at=started_at,
            field_employee_id=field_employee_id,
        )
        frame = CallStartedFrame(
            call_id=call.id,
            field_employee_id=field_employee_id,
            started_at=started_at,
        ).model_dump(mode="json")

        # Fire-and-forget: prewarm caller profile + workspace brain snapshot
        # in the background. The current turn (turn 1) still runs the normal
        # retrieval path — but turn 2+ will find this stash in Redis and the
        # TurnLoop's speculative race will short-circuit cold retrieval.
        from app.deps import get_brain_provider, get_memory_provider
        from app.orchestrator.prewarm import schedule_prewarm

        schedule_prewarm(
            call_id=call.id,
            workspace_id=workspace_id,
            field_employee_id=field_employee_id,
            memory=get_memory_provider(),
            brain=get_brain_provider(),
        )
        return MaterializeResult(workspace_id=workspace_id, call_id=call.id, pending_frames=[frame])

    if isinstance(event, InboundSMS):
        return MaterializeResult(workspace_id=workspace_id, call_id=None, pending_frames=[])

    if isinstance(event, CallEnded):
        existing = await calls.get_by_agentphone_id(event.ap_call_id) if event.ap_call_id else None
        # If the real callId doesn't match, the live turns ran against a
        # synthetic id (ap_<numberId>_<ts>). Find the most-recent in_progress
        # call for this workspace and rewrite its agentphone_call_id to the
        # real one so post-call consumers (summarizer, brain_updater) join
        # on AP's canonical id.
        if existing is None:
            from datetime import UTC, datetime, timedelta

            in_progress = await calls.list_in_progress(workspace_id)
            cutoff = datetime.now(UTC) - timedelta(minutes=20)
            for c in in_progress:
                started = c.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
                if started >= cutoff and c.agentphone_call_id.startswith("ap_"):
                    existing = c
                    if event.ap_call_id:
                        existing.agentphone_call_id = event.ap_call_id
                        await session.flush()
                        log.info(
                            "synthetic_call_id_rewritten",
                            call_id=str(existing.id),
                            real_ap_call_id=event.ap_call_id,
                        )
                    break
        is_new = False
        if existing is None:
            from datetime import UTC, datetime

            existing = await calls.create(
                workspace_id=workspace_id,
                organization_id=ws.organization_id,
                agentphone_call_id=event.ap_call_id,
                from_number=event.from_number or None,
                to_number=event.to_number or None,
                started_at=event.ended_at or datetime.now(UTC),
            )
            is_new = True
        ended_at = event.ended_at or existing.started_at
        await calls.mark_ended(
            existing.id,
            ended_at=ended_at,
            provider_summary={
                "summary": event.provider_summary,
                "user_sentiment": event.user_sentiment,
                "call_successful": event.call_successful,
            }
            if event.provider_summary or event.user_sentiment or event.call_successful is not None
            else None,
        )
        frames: list[dict[str, Any]] = []
        if is_new:
            frames.append(
                CallStartedFrame(
                    call_id=existing.id,
                    field_employee_id=existing.field_employee_id,
                    started_at=existing.started_at,
                ).model_dump(mode="json")
            )
        frames.append(CallEndedFrame(call_id=existing.id, ended_at=ended_at).model_dump(mode="json"))
        return MaterializeResult(workspace_id=workspace_id, call_id=existing.id, pending_frames=frames)

    return MaterializeResult(workspace_id=workspace_id, call_id=None, pending_frames=[])
