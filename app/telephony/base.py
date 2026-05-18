"""TelephonyProvider abstract base.

A telephony provider is the integration layer between AgentPhone (or any
future PSTN-bridge service) and the rest of VotF. The webhook handler
calls `parse_webhook` to translate a raw incoming HTTP request into one of
the `TelephonyEvent` subtypes (see events.py). Outbound paths use
`send_sms` and (Phase 0) `provision_number` at signup.

Returning NDJSON for voice turns is NOT in the provider's responsibility -
the webhook handler builds the StreamingResponse using output from the
Orchestrator (§C4).

See LLD §C3 + HLD §5.1 / §11.2.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.telephony.events import TelephonyEvent


@dataclass(frozen=True)
class ProvisionedNumber:
    phone_number: str  # E.164
    ap_number_id: str
    ap_agent_id: str


class TelephonyProvider(ABC):
    @abstractmethod
    async def provision_number(self, workspace_name: str) -> ProvisionedNumber:
        """Buy a number, create the persona, attach number to persona."""

    @abstractmethod
    async def send_sms(
        self,
        *,
        agent_id: str,
        to_number: str,
        body: str,
        number_id: str | None = None,
    ) -> None:
        """Send an outbound SMS.

        AgentPhone routes by `agent_id`: every AP Agent (= our per-Workspace
        persona) owns one or more numbers, and AP picks a from-number for that
        agent. Pass `number_id` only if the agent owns multiple numbers and
        you want to pin a specific one.

        May raise UpstreamError on provider 5xx.
        """

    @abstractmethod
    def parse_webhook(
        self,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> TelephonyEvent:
        """Translate a verified webhook delivery into a TelephonyEvent.

        Implementations should NOT verify the HMAC here - the webhook
        endpoint (app/api/webhooks/agentphone.py) does that with the shared
        verifier in app.security.hmac. parse_webhook can assume the bytes
        are authenticated and not a replay.
        """

    @abstractmethod
    async def set_conversation_state(
        self,
        ap_conversation_id: str,
        state: dict[str, str],
    ) -> None:
        """PATCH /v1/conversations/{id} so AP echoes our scope on every webhook."""
