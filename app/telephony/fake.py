"""In-memory FakeTelephonyProvider - for tests + the
LLM_API_KEY-empty dev path.

This is NOT a production fallback. The provider factory in app/deps.py picks
this only when AGENTPHONE_API_KEY is empty (signaled with a stderr warning).
In tests, prefer overriding via FastAPI dependency_overrides for explicit
control.
"""

from __future__ import annotations

import secrets
from typing import ClassVar

from app.telephony.base import ProvisionedNumber, TelephonyProvider
from app.telephony.events import (
    InboundSMS,
    InboundVoiceTurn,
    TelephonyEvent,
    WebhookScope,
)


class FakeTelephonyProvider(TelephonyProvider):
    """Returns synthetic numbers; records outbound SMS in memory."""

    _counter: ClassVar[int] = 5550000000

    def __init__(self) -> None:
        self.sent_sms: list[dict[str, str]] = []
        self.conversation_states: dict[str, dict[str, str]] = {}

    async def provision_number(self, workspace_name: str) -> ProvisionedNumber:
        FakeTelephonyProvider._counter += 1
        return ProvisionedNumber(
            phone_number=f"+1{FakeTelephonyProvider._counter}",
            ap_number_id=f"num_fake_{secrets.token_hex(6)}",
            ap_agent_id=f"agt_fake_{secrets.token_hex(6)}",
        )

    async def send_sms(
        self,
        *,
        agent_id: str,
        to_number: str,
        body: str,
        number_id: str | None = None,
    ) -> None:
        self.sent_sms.append(
            {
                "agent_id": agent_id,
                "to_number": to_number,
                "body": body,
                "number_id": number_id or "",
            }
        )

    async def set_conversation_state(self, ap_conversation_id: str, state: dict[str, str]) -> None:
        self.conversation_states[ap_conversation_id] = dict(state)

    def parse_webhook(self, raw_body: bytes, headers: dict[str, str]) -> TelephonyEvent:
        """Test helper: parse a minimal `agent.message` JSON shape.

        Tests typically construct a payload directly rather than going through
        this. It's here so the abstract contract is satisfied; callers can
        either pass real AP-shaped JSON or build TelephonyEvent objects directly.
        """
        import json

        payload = json.loads(raw_body)
        channel = payload.get("channel", "sms")
        data = payload.get("data", {})
        scope_dict = payload.get("conversationState") or {}
        from uuid import UUID

        scope = WebhookScope(
            workspace_id=UUID(scope_dict.get("workspace_id", "00000000-0000-0000-0000-000000000000")),
            field_employee_id=UUID(scope_dict["field_employee_id"])
            if scope_dict.get("field_employee_id")
            else None,
            call_id=UUID(scope_dict["call_id"]) if scope_dict.get("call_id") else None,
        )
        if channel == "voice":
            return InboundVoiceTurn(
                scope=scope,
                ap_call_id=str(data.get("callId", "")),
                from_number=str(data.get("from", "")),
                to_number=str(data.get("to", "")),
                transcript=str(data.get("transcript", "")),
            )
        return InboundSMS(
            scope=scope,
            ap_conversation_id=str(data.get("conversationId", data.get("callId", ""))),
            from_number=str(data.get("from", "")),
            to_number=str(data.get("to", "")),
            body=str(data.get("body", data.get("text", ""))),
            channel=channel,
        )
