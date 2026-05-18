"""AgentPhone adapter - production TelephonyProvider.

Implements the contract in LLD §C3 / HLD §11.2. Endpoints used:

  - POST /v1/agents          (CreateAgentRequest, camelCase fields)
  - POST /v1/numbers         (auto-attach via `agentId`)
  - PATCH /v1/conversations/{id}  (UpdateConversationRequest.metadata)
  - POST /v1/messages        (SendMessageRequest, snake_case fields)

Webhook parse: HMAC verify happens at the endpoint; parse_webhook
translates the verified payload into a TelephonyEvent subtype. Voice
turn response is built by the webhook endpoint as an NDJSON
StreamingResponse - the adapter only parses the inbound event.

Scope resolution policy:
  1. If `conversationState` is present and carries `workspace_id`, use it.
  2. Otherwise the webhook endpoint does a DB lookup by `data.to` against
     ManagerWorkspace.primary_number.

The adapter never hits the DB itself - that keeps it stateless and easy
to unit-test against fixtures. The AP API mixes conventions (camelCase
on /agents and /numbers, snake_case on /messages); the schemas pinned
here match https://docs.agentphone.ai/api-reference.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx

from app.errors import UpstreamError
from app.logging import get_logger
from app.telephony.base import ProvisionedNumber, TelephonyProvider
from app.telephony.events import (
    CallEnded,
    InboundSMS,
    InboundVoiceTurn,
    ReactionReceived,
    TelephonyEvent,
    WebhookScope,
)

BASE_URL = "https://api.agentphone.ai/v1"
log = get_logger(__name__)


class AgentPhoneAdapter(TelephonyProvider):
    """AgentPhone REST client. httpx.AsyncClient is cached at instance
    level — every webhook handler calls set_conversation_state on the first
    voice turn and send_sms during decision pings, so per-call TLS handshake
    overhead is on the hot path. Lifespan shutdown closes the pool."""

    def __init__(self, api_key: str, *, base_url: str = BASE_URL, timeout: float = 15.0) -> None:
        if not api_key:
            raise ValueError("AgentPhoneAdapter requires a non-empty API key")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client_inst: httpx.AsyncClient | None = None
        self._init_lock = asyncio.Lock()

    # ---------------- REST helpers ----------------

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client_inst is not None:
            return self._client_inst
        async with self._init_lock:
            if self._client_inst is not None:
                return self._client_inst
            self._client_inst = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=self._timeout,
            )
        return self._client_inst

    async def close(self) -> None:
        """Drain the connection pool. Called from FastAPI lifespan shutdown."""
        if self._client_inst is not None:
            await self._client_inst.aclose()
            self._client_inst = None

    async def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> Any:
        c = await self._get_client()
        try:
            r = await c.request(method, path, json=json_body)
        except httpx.RequestError as e:
            raise UpstreamError(f"agentphone network error: {e}") from e
        if r.status_code >= 500:
            raise UpstreamError(f"agentphone {r.status_code}", details={"body": r.text[:500]})
        if r.status_code >= 400:
            raise UpstreamError(
                f"agentphone rejected {method} {path}: {r.status_code}",
                details={"body": r.text[:500]},
            )
        if not r.content:
            return None
        try:
            return r.json()
        except json.JSONDecodeError as e:
            raise UpstreamError(f"agentphone returned non-JSON: {e}") from e

    # ---------------- Provisioning ----------------

    async def provision_number(self, workspace_name: str) -> ProvisionedNumber:
        # POST /v1/agents uses camelCase per CreateAgentRequest.
        # See https://docs.agentphone.ai/api-reference (CreateAgentRequest schema).
        agent_resp = await self._request(
            "POST",
            "/agents",
            json_body={
                "name": f"VotF / {workspace_name}",
                "voiceMode": "webhook",  # our backend owns the conversation
                "enableMessaging": True,
            },
        )
        ap_agent_id = self._extract_id(agent_resp, "agent")

        # POST /v1/numbers accepts `agentId` to auto-attach in one call, saving
        # a follow-up POST /v1/agents/{id}/numbers.
        number_resp = await self._request(
            "POST",
            "/numbers",
            json_body={"country": "US", "agentId": ap_agent_id},
        )
        ap_number_id = self._extract_id(number_resp, "number")
        phone_number = (
            number_resp.get("phoneNumber") or number_resp.get("phone_number") or number_resp.get("e164")
        )
        if not phone_number:
            raise UpstreamError(
                "agentphone /numbers response missing phoneNumber",
                details={"keys": list(number_resp)},
            )

        log.info(
            "agentphone_provisioned",
            workspace=workspace_name,
            phone_number=phone_number,
            ap_agent_id=ap_agent_id,
            ap_number_id=ap_number_id,
        )
        return ProvisionedNumber(
            phone_number=phone_number,
            ap_number_id=ap_number_id,
            ap_agent_id=ap_agent_id,
        )

    @staticmethod
    def _extract_id(response: dict[str, Any], kind: str) -> str:
        # AP responses sometimes wrap the id in an object, sometimes inline.
        candidate = response.get("id") or response.get(f"{kind}Id") or response.get(f"{kind}_id")
        if not candidate:
            raise UpstreamError(
                f"agentphone {kind} response missing id",
                details={"keys": list(response)},
            )
        return str(candidate)

    # ---------------- Outbound SMS ----------------

    async def send_sms(
        self,
        *,
        agent_id: str,
        to_number: str,
        body: str,
        number_id: str | None = None,
    ) -> None:
        # POST /v1/messages uses snake_case per SendMessageRequest. AP routes
        # by agent_id (every AP Agent owns one or more numbers); pass
        # number_id only when an agent owns multiple and we need to pin one.
        payload: dict[str, Any] = {
            "agent_id": agent_id,
            "to_number": to_number,
            "body": body,
        }
        if number_id is not None:
            payload["number_id"] = number_id
        await self._request("POST", "/messages", json_body=payload)

    # ---------------- Conversation metadata ----------------

    async def set_conversation_state(
        self,
        ap_conversation_id: str,
        state: dict[str, str],
    ) -> None:
        await self._request(
            "PATCH",
            f"/conversations/{ap_conversation_id}",
            json_body={"metadata": state},
        )

    # ---------------- Webhook parsing ----------------

    def parse_webhook(
        self,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> TelephonyEvent:
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as e:
            raise UpstreamError(f"agentphone webhook body not JSON: {e}") from e
        return self._from_payload(payload)

    def _from_payload(self, payload: dict[str, Any]) -> TelephonyEvent:
        event_type = payload.get("event") or payload.get("type")
        channel = payload.get("channel") or payload.get("data", {}).get("channel")
        data: dict[str, Any] = payload.get("data") or {}

        # Top-level agentId is the ONLY reliable identifier on live voice turns
        # (data.callId / data.from / data.to often arrive empty).
        ap_agent_id = str(payload.get("agentId") or "")
        scope = self._resolve_scope(payload.get("conversationState") or {})
        ts = _parse_timestamp(payload.get("timestamp"))

        if event_type == "agent.message" and channel == "voice":
            return InboundVoiceTurn(
                scope=scope,
                ap_call_id=str(data.get("callId") or ""),
                ap_number_id=str(data.get("numberId") or ""),
                ap_agent_id=ap_agent_id,
                from_number=str(data.get("from") or ""),
                to_number=str(data.get("to") or ""),
                transcript=str(data.get("transcript") or ""),
                confidence=float(data.get("confidence") or 0.0),
                direction=str(data.get("direction") or "inbound"),  # type: ignore[arg-type]
                delivery_timestamp=ts,
            )
        if event_type == "agent.message":
            return InboundSMS(
                scope=scope,
                channel=str(channel or "sms"),  # type: ignore[arg-type]
                ap_conversation_id=str(data.get("conversationId") or data.get("callId") or ""),
                from_number=str(data.get("from") or ""),
                to_number=str(data.get("to") or ""),
                body=str(data.get("body") or data.get("text") or ""),
                delivery_timestamp=ts,
            )
        if event_type == "agent.call_ended":
            # AP serializes data.transcript as a list of turn objects on call_ended;
            # join them for storage as a single string.
            raw_transcript = data.get("transcript")
            if isinstance(raw_transcript, list):
                full_transcript = "\n".join(
                    f"{t.get('role','?')}: {t.get('content','')}"
                    for t in raw_transcript
                    if isinstance(t, dict)
                )
            else:
                full_transcript = str(raw_transcript or "")
            return CallEnded(
                scope=scope,
                ap_call_id=str(data.get("callId") or ""),
                ap_number_id=str(data.get("numberId") or ""),
                ap_agent_id=ap_agent_id,
                from_number=str(data.get("from") or ""),
                to_number=str(data.get("to") or ""),
                full_transcript=full_transcript,
                provider_summary=data.get("summary"),
                user_sentiment=data.get("userSentiment"),
                call_successful=data.get("callSuccessful"),
                ended_at=_parse_timestamp(data.get("endedAt")) or ts,
            )
        if event_type == "agent.reaction":
            return ReactionReceived(
                scope=scope,
                ap_conversation_id=str(data.get("conversationId") or ""),
                reaction_type=str(data.get("reaction") or ""),
            )
        raise UpstreamError(
            f"unknown AgentPhone event: event={event_type!r} channel={channel!r}",
            details={"event": event_type, "channel": channel},
        )

    @staticmethod
    def _resolve_scope(conversation_state: dict[str, Any]) -> WebhookScope:
        """Extract scope from the conversationState echo, if present.

        If AP echoes our metadata, we skip a DB lookup. Otherwise the webhook
        endpoint will fall back to ManagerWorkspace.where(primary_number=to).
        """
        wid = conversation_state.get("workspace_id")
        if not wid:
            return WebhookScope(workspace_id=UUID(int=0))  # sentinel; endpoint will resolve
        return WebhookScope(
            workspace_id=UUID(str(wid)),
            field_employee_id=UUID(conversation_state["field_employee_id"])
            if conversation_state.get("field_employee_id")
            else None,
            call_id=UUID(conversation_state["call_id"]) if conversation_state.get("call_id") else None,
        )


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
