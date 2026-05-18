"""SMS orchestrator — conversational SMS counterpart to the voice TurnLoop.

Architecture mirrors voice but the wire-shape differs:

  Voice                              SMS
  ----------------------------       ----------------------------
  AP fires webhook per turn          AP fires webhook per inbound message
  Stream NDJSON chunks back          One outbound SMS via telephony.send_sms
  AP TTS speaks chunks               AP gateway delivers the SMS
  call.ended fires post-call         No end event — conversation runs open

Reuses every Phase 0 building block: Call rows (with prefix `sms_<conv>`),
TranscriptFragment, Retriever, RedisSessionStore, ToolRegistry. The only
new piece is the request-shape adapter + a tuned prompt that drops the
voice-specific `end_call` tool and tells the model it's SMS.

[DR-XXXXXX] decision-response handling is preserved from the Phase 0
default handler — see `_handle_decision_response`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.db.app_session import app_session
from app.db.repositories.calls_repo import CallsRepo
from app.db.repositories.field_employees_repo import FieldEmployeesRepo
from app.db.repositories.transcripts_repo import TranscriptsRepo
from app.db.repositories.workspaces_repo import WorkspacesRepo
from app.deps import (
    get_brain_provider,
    get_memory_provider,
    get_telephony_provider,
)
from app.errors import NotFound
from app.logging import get_logger
from app.orchestrator.retrieval import Retriever
from app.orchestrator.session import RedisSessionStore
from app.orchestrator.tool_dispatch import scan_for_tool_calls
from app.orchestrator.tools import ToolContext, ToolRegistry
from app.settings import get_settings
from app.skills import get_llm_client
from app.telephony.dispatcher import SMSHandler, get_dispatcher
from app.telephony.events import InboundSMS

log = get_logger(__name__)


SMS_TOOLS_ALLOWED = {"request_manager_decision"}  # `end_call` doesn't apply to SMS


class SMSOrchestratorHandler:
    """Production SMSHandler. Routes:

      - `[DR-XXXXXX] ...` from the workspace Manager → DecisionService
        (existing Phase 0 behavior, preserved)
      - everything else → conversational orchestration

    Conversational orchestration shape per inbound SMS:

      1. Resolve workspace (already in event.scope from dispatcher) +
         FieldEmployee (by from_number; create unprofiled if new).
      2. Find/create the SMS Call row keyed on `sms_<ap_conversation_id>`
         (sticky across messages in the same AP conversation).
      3. Persist the inbound message as a TranscriptFragment(speaker=caller).
      4. Load/create Redis session; append caller turn to conversation history.
      5. Retrieve context (Supermemory + Brain) — no streaming pressure, can
         take a few hundred ms.
      6. Render an SMS-tuned prompt and call the LLM (non-streaming).
      7. Strip tool markers from spoken text; dispatch any tool calls
         (request_manager_decision is the only SMS-relevant one for now).
      8. Persist the agent reply, save session, send the SMS via AP.
    """

    async def handle(self, event: InboundSMS, *, workspace_id: UUID) -> None:
        body = event.body.strip()

        # Preserve the Phase 0 [DR-...] decision-response path verbatim.
        if body.startswith("[DR-"):
            await self._handle_decision_response(event, workspace_id=workspace_id)
            return

        # Conversational orchestration.
        try:
            await self._handle_conversational(event, workspace_id=workspace_id)
        except Exception:
            log.exception(
                "sms_orchestrator_failed",
                from_number=event.from_number,
                channel=event.channel,
                workspace_id=str(workspace_id),
            )

    # ---------------- Decision-response path (unchanged from Phase 0) ----------------

    async def _handle_decision_response(self, event: InboundSMS, *, workspace_id: UUID) -> None:
        from app.services.decisions import DecisionService

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
                log.info("inbound_sms_dr_no_match", body_preview=event.body[:120])

    # ---------------- Conversational path ----------------

    async def _handle_conversational(self, event: InboundSMS, *, workspace_id: UUID) -> None:
        # Step 1-3: resolve workspace + FieldEmployee, materialize SMS Call,
        # persist the inbound fragment.
        call_id, workspace, field_employee, now = await self._materialize(event, workspace_id=workspace_id)
        if call_id is None:
            return  # logged inside _materialize

        # Step 4: load Redis session, append caller turn.
        session_store = RedisSessionStore()
        sess = await session_store.load_or_create(
            call_id=call_id,
            workspace_id=workspace.id,
            field_employee_id=field_employee.id if field_employee else None,
        )
        sess.append_turn(speaker="caller", text=event.body, ts=now)

        # Step 5: retrieval. SMS has no AP-30s timeout pressure so we await
        # in full (no bridge chunk, no speculative race needed).
        retriever = Retriever(memory=get_memory_provider(), brain=get_brain_provider())
        context = await retriever.for_turn(
            workspace_id=workspace.id,
            field_employee_id=field_employee.id if field_employee else None,
            query=event.body,
        )

        # Step 6: render SMS prompt + call LLM (non-streaming — we collect
        # the full reply before sending the single outbound SMS).
        messages = _render_sms_messages(
            workspace=workspace,
            field_employee=field_employee,
            session_history=sess.conversation_history,
            context=context,
            inbound_text=event.body,
        )
        llm = get_llm_client()
        model = get_settings().llm_default_model
        full_reply, tool_calls = await _collect_llm_reply(llm, model, messages)

        # Step 7: dispatch any tool calls (request_manager_decision only).
        bridge_texts: list[str] = []
        for tc in tool_calls:
            if tc["name"] not in SMS_TOOLS_ALLOWED:
                log.info(
                    "sms_tool_call_skipped_not_allowed",
                    tool=tc["name"],
                    call_id=str(call_id),
                )
                continue
            try:
                result = await ToolRegistry.dispatch(
                    ToolContext(
                        workspace_id=workspace.id,
                        call_id=call_id,
                        field_employee_id=field_employee.id if field_employee else None,
                    ),
                    tc["name"],
                    tc["args"],
                )
                if result.bridge_text:
                    bridge_texts.append(result.bridge_text)
                if result.followup_context:
                    new_did = result.followup_context.get("decision_id")
                    if new_did and str(new_did) not in sess.pending_decisions:
                        sess.pending_decisions.append(str(new_did))
            except Exception as e:
                log.exception(
                    "sms_tool_dispatch_failed",
                    tool=tc["name"],
                    call_id=str(call_id),
                )
                bridge_texts.append(
                    f"(I tried to flag that to your manager but hit an error: {type(e).__name__}.)"
                )

        # Compose the final outbound body: spoken text + any tool bridge texts.
        outbound_body = full_reply.strip()
        if bridge_texts:
            outbound_body = (outbound_body + "\n\n" + "\n".join(bridge_texts)).strip()
        if not outbound_body:
            outbound_body = "Got it."

        # SMS gateways usually cap segments at ~160/1600 chars. Trim hard.
        if len(outbound_body) > 1400:
            outbound_body = outbound_body[:1397].rstrip() + "..."

        # Step 8a: persist the agent fragment + save session.
        agent_ts = datetime.now(UTC)
        async with app_session() as s2:
            await TranscriptsRepo(s2).append(
                call_id=call_id,
                workspace_id=workspace.id,
                speaker="agent",
                text=outbound_body,
                ts=agent_ts,
            )
            await s2.commit()
        sess.append_turn(speaker="agent", text=outbound_body, ts=agent_ts)
        try:
            await session_store.save(sess)
        except Exception as e:
            # Non-fatal — durable transcript is in Postgres.
            log.warning("sms_session_save_failed", call_id=str(call_id), error=str(e))

        # Step 8b: send the SMS via AP.
        await self._send_sms_reply(workspace, to_number=event.from_number, body=outbound_body)

    # ---------------- Helpers ----------------

    async def _materialize(
        self, event: InboundSMS, *, workspace_id: UUID
    ) -> tuple[UUID | None, Any, Any, datetime]:
        """Return (call_id, workspace, field_employee, now). On unknown
        workspace returns (None, None, None, now) and logs.
        """
        now = event.delivery_timestamp or datetime.now(UTC)
        async with app_session() as session:
            workspaces = WorkspacesRepo(session)
            fes = FieldEmployeesRepo(session)
            calls = CallsRepo(session)
            transcripts = TranscriptsRepo(session)

            ws = await workspaces.get_by_id(workspace_id)
            if ws is None:
                log.warning(
                    "sms_unknown_workspace",
                    workspace_id=str(workspace_id),
                    from_number=event.from_number,
                )
                return None, None, None, now

            # Resolve or create FieldEmployee by sender phone.
            fe = None
            if event.from_number:
                fe = await fes.find_by_phone(ws.id, event.from_number)
                if fe is None:
                    fe = await fes.create_unprofiled(
                        workspace_id=ws.id,
                        organization_id=ws.organization_id,
                        phone=event.from_number,
                    )

            # SMS Call key: sms_<ap_conversation_id> when present, else fall
            # back to sms_<workspace>_<from_number> so messages from the same
            # number sticky-join.
            sms_key = (
                f"sms_{event.ap_conversation_id}"
                if event.ap_conversation_id
                else f"sms_{ws.id}_{event.from_number or 'unknown'}"
            )
            existing = await calls.get_by_agentphone_id(sms_key)
            if existing is None:
                call = await calls.create(
                    workspace_id=ws.id,
                    organization_id=ws.organization_id,
                    agentphone_call_id=sms_key,
                    from_number=event.from_number or None,
                    to_number=event.to_number or ws.primary_number or None,
                    started_at=now,
                    field_employee_id=fe.id if fe else None,
                )
                call_id = call.id
                log.info(
                    "sms_conversation_started",
                    call_id=str(call_id),
                    sms_key=sms_key,
                    channel=event.channel,
                )
            else:
                call_id = existing.id

            # Persist inbound fragment.
            await transcripts.append(
                call_id=call_id,
                workspace_id=ws.id,
                speaker="caller",
                text=event.body,
                ts=now,
            )
            await session.commit()
            return call_id, ws, fe, now

    async def _send_sms_reply(self, workspace: Any, *, to_number: str, body: str) -> None:
        if not workspace.agentphone_agent_id:
            log.error(
                "sms_reply_missing_agent_id",
                workspace_id=str(workspace.id),
                to_number=to_number,
            )
            return
        if not to_number:
            log.error("sms_reply_missing_to_number", workspace_id=str(workspace.id))
            return
        telephony = get_telephony_provider()
        try:
            await telephony.send_sms(
                agent_id=workspace.agentphone_agent_id,
                to_number=to_number,
                body=body,
                number_id=workspace.agentphone_number_id or None,
            )
            log.info(
                "sms_reply_sent",
                workspace_id=str(workspace.id),
                to_number=to_number,
                length=len(body),
            )
        except Exception:
            # AP may reject (e.g. 10DLC not provisioned). Log; don't raise — the
            # webhook handler must still return 200 to AP.
            log.exception(
                "sms_reply_send_failed",
                workspace_id=str(workspace.id),
                to_number=to_number,
            )


# ---------------- Prompt building ----------------


def _render_sms_messages(
    *,
    workspace: Any,
    field_employee: Any | None,
    session_history: list[Any],
    context: Any,
    inbound_text: str,
) -> list[dict[str, str]]:
    """Build SMS-tuned chat messages.

    Different from the voice prompt:
      - Tells the model it's SMS (text, no TTS, no streaming).
      - "Reply in 1–2 short sentences. No greetings or sign-offs after the
        first message."
      - Only one tool is in scope: request_manager_decision.
    """
    caller_name = field_employee.name if field_employee is not None else "the Rep"
    caller_role = (field_employee.role or "field rep") if field_employee is not None else "field rep"
    workspace_name = workspace.name

    system_lines = [
        f"You are the {workspace_name} agent corresponding with {caller_name} ({caller_role}) over SMS.",
        "This is a text-message conversation — not a voice call. Reply in 1-2 short sentences.",
        "Do not greet the user after the first message. Do not sign your name. Do not send links.",
        "Stay focused: ask one sharp question at a time, capture what they share, escalate to the manager when warranted.",
        "",
        "## Tools",
        "You may invoke ONE tool per reply by appending a marker at the very end:",
        '  <<TOOL request_manager_decision {"prompt":"...","options":["..."],"decision_class":"inline|bridged|async","rationale":"..."}>>',
        "Only use the tool when the question genuinely needs the Manager's judgment. The text BEFORE the marker is what the Rep reads as the SMS body.",
        "Do not invoke any other tool over SMS.",
    ]
    system_msg = "\n".join(system_lines)

    user_lines: list[str] = []
    if context.caller_profile and context.caller_profile.summary:
        user_lines.append(f"## What we know about {caller_name}")
        user_lines.append(context.caller_profile.summary.strip())
        user_lines.append("")
    if context.caller_hits:
        user_lines.append("## Recent context from this Rep")
        for h in context.caller_hits[:5]:
            snippet = (h.content or "").strip()[:240]
            if snippet:
                user_lines.append(f"- {snippet}")
        user_lines.append("")
    if context.brain_hits:
        user_lines.append("## Relevant workspace knowledge")
        for h in context.brain_hits[:5]:
            title = h.title or h.slug
            snip = (h.snippet or "").strip()[:240]
            user_lines.append(f"- [{h.slug}] {title} — {snip}")
        user_lines.append("")
    if session_history:
        user_lines.append("## Conversation so far")
        for turn in session_history[-12:]:
            speaker = "Rep" if turn.speaker == "caller" else "You"
            user_lines.append(f"{speaker}: {turn.text}")
        user_lines.append("")
    user_lines.append(f"## New message from {caller_name}")
    user_lines.append(inbound_text)
    user_lines.append("")
    user_lines.append(
        "Reply now in 1-2 short sentences. Do not preface ('Sure', 'Got it') unless that IS the whole reply."
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": "\n".join(user_lines)},
    ]


async def _collect_llm_reply(
    llm: Any, model: str, messages: list[dict[str, str]]
) -> tuple[str, list[dict[str, Any]]]:
    """Run a non-streaming-style accumulation: stream tokens, scan for tool
    markers, return (spoken_text, [tool_call_dicts]).
    """
    token_iter = llm.stream_chat(model=model, messages=messages, max_tokens=400)
    spoken: list[str] = []
    tools: list[dict[str, Any]] = []
    async for kind, payload in scan_for_tool_calls(token_iter):
        if kind == "text":
            spoken.append(payload)
        elif kind == "tool_call":
            tools.append(payload)
        elif kind == "error":
            log.warning("sms_tool_marker_error", detail=str(payload))
        elif kind == "done":
            break
    return "".join(spoken), tools


# ---------------- Registration ----------------


def register_sms_with_dispatcher() -> None:
    """Replace the Phase 0 default SMS handler with the orchestrator.

    Called once at startup from app/lifespan.py.
    """
    handler: SMSHandler = SMSOrchestratorHandler()
    get_dispatcher().set_sms_handler(handler)


__all__ = ["SMSOrchestratorHandler", "register_sms_with_dispatcher"]
