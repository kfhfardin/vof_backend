"""DecisionService.

Two flows per LLD §C6:

  open()    - called by the request_manager_decision tool. Persists the row,
              publishes decision.opened to the Workspace WS bus, sends an
              SMS to the Manager's mobile (if available), and (Phase 0)
              returns immediately. Timeout scheduling is §C7.

  respond() - called by the FE endpoint OR by the inbound-SMS handler.
              SELECT FOR UPDATE on the row prevents two responders from both
              succeeding (first-responder-wins per LLD §C6). On success,
              publishes decision.resolved to the WS bus.

The class is callable from both the orchestrator hot path (via a tool) and
the API surface (via /respond). Both end up writing to the same row + bus.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DecisionClass, DecisionRequest, RespondedVia
from app.db.repositories.decisions_repo import DecisionsRepo
from app.db.repositories.workspaces_repo import WorkspacesRepo
from app.errors import Conflict, NotFound, Validation
from app.logging import get_logger
from app.realtime.bus import publish_frame
from app.schemas.ws_frames import DecisionOpenedFrame, DecisionResolvedFrame
from app.telephony.base import TelephonyProvider

log = get_logger(__name__)

DEFAULT_TIMEOUTS_SECONDS: dict[DecisionClass, int | None] = {
    "inline": 45,
    "bridged": 120,
    "async": None,
}


def _short_id(decision_id: UUID) -> str:
    """First 6 hex chars of the decision id - used as the SMS prefix."""
    return decision_id.hex[:6].upper()


class DecisionService:
    def __init__(
        self,
        session: AsyncSession,
        telephony: TelephonyProvider | None = None,
    ) -> None:
        self.session = session
        self.repo = DecisionsRepo(session)
        self._telephony = telephony

    # ---------------- Open ----------------

    async def open(
        self,
        *,
        call_id: UUID,
        workspace_id: UUID,
        prompt: str,
        options: list[str],
        decision_class: DecisionClass,
        context: dict[str, Any] | None = None,
        manager_phone: str | None = None,
        agentphone_agent_id: str | None = None,
    ) -> DecisionRequest:
        if not options:
            raise Validation("decision must offer at least one option")
        if decision_class not in DEFAULT_TIMEOUTS_SECONDS:
            raise Validation(f"unknown decision_class: {decision_class}")

        # Phase 0: target is always the Workspace's Manager.
        workspaces = WorkspacesRepo(self.session)
        ws = await workspaces.get_by_id(workspace_id)
        if ws is None:
            raise NotFound(f"workspace {workspace_id} not found")
        if ws.manager_user_id is None:
            raise Validation("workspace has no manager_user_id assigned")

        timeout_seconds = DEFAULT_TIMEOUTS_SECONDS[decision_class]
        timeout_at = datetime.now(UTC) + timedelta(seconds=timeout_seconds) if timeout_seconds else None

        decision = await self.repo.create(
            call_id=call_id,
            workspace_id=workspace_id,
            target_user_id=ws.manager_user_id,
            prompt=prompt,
            options=options,
            decision_class=decision_class,
            timeout_at=timeout_at,
            context=context,
        )
        await self.session.commit()

        # Best-effort side effects (don't roll back the DB row on failure).
        await self._publish_opened(decision)
        if manager_phone and agentphone_agent_id and self._telephony is not None:
            await self._send_sms_ping(
                decision, to=manager_phone, agent_id=agentphone_agent_id
            )

        # Schedule the timeout for inline/bridged classes (async has no
        # live wait; surfaces post-call via DecisionsRepo.list_for_workspace).
        if timeout_at is not None:
            try:
                from app.workers.decision_timeout import schedule_or_inline

                await schedule_or_inline(decision.id, timeout_at)
            except Exception:
                log.exception(
                    "decision_timeout_schedule_failed",
                    decision_id=str(decision.id),
                    workspace_id=str(decision.workspace_id),
                )

        return decision

    # ---------------- Respond ----------------

    async def respond(
        self,
        *,
        decision_id: UUID,
        responder_user_id: UUID,
        response: str,
        via: RespondedVia,
    ) -> DecisionRequest:
        """First-responder-wins. Raises Conflict if already resolved."""
        decision = await self.repo.lock_for_update(decision_id)
        if decision is None:
            raise NotFound(f"decision {decision_id} not found")
        if decision.status != "open":
            raise Conflict(
                "decision_already_resolved",
                details={"status": decision.status, "responded_via": decision.responded_via},
            )
        if response not in decision.options:
            raise Validation(
                "response not among offered options",
                details={"response": response, "options": decision.options},
            )

        now = datetime.now(UTC)
        decision = await self.repo.mark_answered(
            decision,
            response=response,
            responded_by_user_id=responder_user_id,
            via=via,
            responded_at=now,
        )
        await self.session.commit()
        await self._publish_resolved(decision)
        return decision

    # ---------------- Inbound SMS matcher ----------------

    async def match_sms_response(
        self,
        *,
        body: str,
        manager_user_id: UUID,
    ) -> DecisionRequest | None:
        """If the SMS body matches `[DR-XXXXXX] <option>` and the prefix
        resolves to an open decision the user is targeted on, mark it
        answered and return the row. Returns None if no match (caller
        treats as brain-write or noise).

        Note: this trusts the caller to verify that the sending phone number
        actually belongs to manager_user_id. The dispatcher resolves the
        Manager from the workspace scope, not from the inbound number, so
        spoofing the from-number wouldn't grant decision-respond access here.
        """
        body = body.strip()
        if not body.startswith("[DR-"):
            return None
        close_bracket = body.find("]")
        if close_bracket == -1:
            return None
        short = body[4:close_bracket].strip().upper()
        rest = body[close_bracket + 1 :].strip()
        if not short or not rest:
            return None

        # Scan open decisions for this user; match the short prefix.
        candidates = await self.repo.list_open_for_user(manager_user_id)
        for d in candidates:
            if _short_id(d.id) != short:
                continue
            # Match the response to one of the offered options (case-insensitive).
            chosen: str | None = next((opt for opt in d.options if opt.lower() == rest.lower()), None)
            if chosen is None:
                # The Manager typed something that didn't match - return the
                # row so the caller can ask for clarification.
                return d
            return await self.respond(
                decision_id=d.id,
                responder_user_id=manager_user_id,
                response=chosen,
                via="sms",
            )
        return None

    # ---------------- Internals ----------------

    async def _publish_opened(self, decision: DecisionRequest) -> None:
        frame = DecisionOpenedFrame(
            call_id=decision.call_id,
            decision_id=decision.id,
            prompt=decision.prompt,
            options=decision.options,
            decision_class=decision.decision_class,
            timeout_at=decision.timeout_at,
        ).model_dump(mode="json")
        await publish_frame(decision.workspace_id, frame)

    async def _publish_resolved(self, decision: DecisionRequest) -> None:
        frame = DecisionResolvedFrame(
            call_id=decision.call_id,
            decision_id=decision.id,
            response=decision.response,
            responded_via=decision.responded_via or "websocket",
        ).model_dump(mode="json")
        await publish_frame(decision.workspace_id, frame)

    async def _send_sms_ping(
        self,
        decision: DecisionRequest,
        *,
        to: str,
        agent_id: str,
    ) -> None:
        if self._telephony is None:
            return
        prefix = _short_id(decision.id)
        opts_text = " | ".join(decision.options)
        body = f"[DR-{prefix}] {decision.prompt}\n\nReply with one of: {opts_text}"
        try:
            await self._telephony.send_sms(agent_id=agent_id, to_number=to, body=body)
        except Exception:
            log.exception(
                "decision_sms_dispatch_failed",
                decision_id=str(decision.id),
                workspace_id=str(decision.workspace_id),
            )
