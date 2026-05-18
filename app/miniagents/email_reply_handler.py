"""email_reply_handler mini-agent (Phase 1 §F6, trigger=http).

AgentMail webhook -> normalized AgentMailEvent -> here.

Speed-variant routing:
  - Drop non-`message.received` events (bounce/complaint/delivered just log).
  - Re-fetch full body if the webhook payload was truncated.
  - Find the parent EmailMessage row via In-Reply-To / References. If we
    can't, drop (we don't accept unsolicited inbound).
  - From-address direct match against the Workspace's manager email ->
    open a CorrectionIntake with origin="manager_email_reply".
  - From-address direct match against a FieldEmployee.email -> write an
    IntakeBufferItem with source="rep_email_followup" (the value the
    foundation agent's 0010 migration enabled at the DB level).
  - Unknown sender -> log and drop.

No Talon quoted-history extraction; raw text passes through.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.db.app_session import app_session
from app.db.repositories.email_messages_repo import EmailMessagesRepo
from app.db.repositories.field_employees_repo import FieldEmployeesRepo
from app.db.repositories.intake_repo import IntakeRepo
from app.db.repositories.workspaces_repo import WorkspacesRepo
from app.email.agentmail import AgentMailEmailProvider
from app.email.schemas import AgentMailEvent
from app.logging import get_logger
from app.services.correction_intake import open_correction_intake

log = get_logger(__name__)


async def handle_event(event: AgentMailEvent) -> None:
    msg = event.message
    inbox_id = msg.inbox_id or ""

    async with app_session() as session:
        ws_repo = WorkspacesRepo(session)
        ws = await ws_repo.get_by_email_inbox_id(inbox_id) if inbox_id else None
        if ws is None:
            log.warning("agentmail_webhook_unknown_inbox", inbox_id=inbox_id)
            return

        if event.event_type != "message.received":
            log.info(
                "agentmail_webhook_dropped_non_received",
                event_type=event.event_type,
                workspace_id=str(ws.id),
            )
            return

        # Re-fetch the body if AgentMail truncated.
        if msg.text is None and msg.html is None:
            try:
                provider = AgentMailEmailProvider()
                msg = await provider.get_full_message(
                    inbox_id=inbox_id,
                    oauth_user_id=None,
                    message_id=msg.message_id,
                )
            except Exception:
                log.exception("agentmail_full_message_fetch_failed", message_id=msg.message_id)

        # Correlate to a parent we sent.
        emails = EmailMessagesRepo(session)
        candidate_ids: list[str] = []
        if msg.in_reply_to:
            candidate_ids.extend(msg.in_reply_to)
        if msg.references:
            candidate_ids.extend(msg.references)
        parents = await emails.find_by_provider_message_ids(candidate_ids)
        parent = next((p for p in parents if p.workspace_id == ws.id), None)
        if parent is None and candidate_ids:
            # LLD §F6: one 500ms backoff retry, in case the reply landed
            # before the parent's commit was visible (rare race when AgentMail
            # delivers a webhook just after our send returns).
            await asyncio.sleep(0.5)
            parents = await emails.find_by_provider_message_ids(candidate_ids)
            parent = next((p for p in parents if p.workspace_id == ws.id), None)
        if parent is None:
            log.info(
                "dropped_orphan_reply",
                from_=(msg.from_[0] if msg.from_ else None),
                workspace_id=str(ws.id),
            )
            return

        # Sender routing.
        from_addr = (msg.from_[0] if msg.from_ else "").strip().lower()
        manager_email = await ws_repo.get_manager_email(ws.id)
        sender_role: str = "unknown"
        rep: Any = None
        if manager_email and from_addr == manager_email.lower():
            sender_role = "manager"
        elif from_addr:
            fes = FieldEmployeesRepo(session)
            rep = await fes.get_by_email(ws.id, from_addr)
            if rep is not None:
                sender_role = "rep"

        reply_body = msg.text or ""

        if sender_role == "manager":
            if ws.manager_user_id is None:
                log.warning(
                    "manager_correction_skipped_no_manager_user",
                    workspace_id=str(ws.id),
                )
                return
            intake_id = await open_correction_intake(
                session,
                workspace_id=ws.id,
                organization_id=ws.organization_id,
                target_user_id=ws.manager_user_id,
                origin="manager_email_reply",
                source_ref_id=parent.trigger_ref_id,
                payload={
                    "reply_body": reply_body,
                    "from_addr": from_addr,
                    "subject": msg.subject or "",
                    "parent_email_message_id": str(parent.id),
                    "parent_trigger_kind": parent.trigger_kind,
                },
            )
            await session.commit()
            log.info(
                "agentmail_reply_routed_to_manager_correction",
                workspace_id=str(ws.id),
                correction_intake_id=str(intake_id),
                parent_email_message_id=str(parent.id),
            )
            return

        if sender_role == "rep":
            # IntakeBufferItem.submitted_by_user_id is a FK to users.id, so
            # resolve the Rep's User row. Falls back to the Manager's user_id
            # if the Rep doesn't yet have an account (older Phase 0 reps).
            from sqlalchemy import select

            from app.db.models import User

            user_q = await session.execute(
                select(User.id)
                .where(User.field_employee_id == rep.id)
                .limit(1)
            )
            submitted_by = user_q.scalar_one_or_none() or ws.manager_user_id
            if submitted_by is None:
                log.warning(
                    "rep_email_followup_no_submitter",
                    workspace_id=str(ws.id),
                    field_employee_id=str(rep.id),
                )
                return
            intake = IntakeRepo(session)
            item = await intake.create(
                workspace_id=ws.id,
                organization_id=ws.organization_id,
                submitted_by_user_id=submitted_by,
                source="rep_email_followup",
                purpose="ongoing_update",
                content_text=reply_body,
            )
            item.classification = {
                "via": "email_reply",
                "call_id": str(parent.trigger_ref_id),
                "field_employee_id": str(rep.id),
                "parent_email_message_id": str(parent.id),
                "timestamp": (
                    msg.timestamp.isoformat()
                    if hasattr(msg.timestamp, "isoformat")
                    else str(msg.timestamp)
                ),
            }
            await session.flush()
            await session.commit()
            log.info(
                "agentmail_reply_routed_to_rep_followup",
                workspace_id=str(ws.id),
                field_employee_id=str(rep.id),
                intake_id=str(item.id),
                parent_email_message_id=str(parent.id),
            )
            return

        log.info(
            "dropped_unknown_sender",
            from_=from_addr,
            workspace_id=str(ws.id),
        )
