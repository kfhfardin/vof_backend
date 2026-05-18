"""Telephony event types - the discriminated union the webhook adapter produces.

Each AgentPhone webhook delivery (after HMAC verify + replay-window check +
dedupe) is translated into one of these. The webhook handler dispatches
based on the event subtype to the right consumer (orchestrator, SMS handler,
post-call worker).

See LLD §C3 + HLD §11.2.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class WebhookScope:
    """Resolved scope from `conversationState` (echo) or DB lookup-by-number."""

    workspace_id: UUID
    field_employee_id: UUID | None = None  # null for unprofiled callers
    call_id: UUID | None = None  # set once a Call row exists


@dataclass(frozen=True)
class InboundVoiceTurn:
    """`agent.message:voice` - a single transcribed Rep utterance.

    The webhook response must stream NDJSON chunks back; the orchestrator
    (§C4) consumes this event and produces the chunks.

    Field availability quirk: AP delivers live voice turns with `callId`,
    `from`, and `to` all empty/null — only `numberId` and the top-level
    `agentId` identify the line. Scope resolution must fall back through
    to_number → ap_number_id → ap_agent_id, and call materialization must
    synthesize a call from "most recent in_progress for this workspace"
    when ap_call_id is empty.
    """

    kind: Literal["voice_turn"] = field(default="voice_turn", init=False)
    scope: WebhookScope = field(default=None)  # type: ignore[assignment]
    ap_call_id: str = ""
    ap_number_id: str = ""
    ap_agent_id: str = ""  # top-level agentId from payload
    from_number: str = ""  # E.164 (often empty on AP voice webhooks)
    to_number: str = ""  # E.164 (often empty on AP voice webhooks)
    transcript: str = ""
    confidence: float = 0.0
    direction: Literal["inbound", "outbound"] = "inbound"
    delivery_timestamp: datetime | None = None


@dataclass(frozen=True)
class InboundSMS:
    """`agent.message` with channel in {sms, mms, imessage}."""

    kind: Literal["sms"] = field(default="sms", init=False)
    scope: WebhookScope = field(default=None)  # type: ignore[assignment]
    channel: Literal["sms", "mms", "imessage"] = "sms"
    ap_conversation_id: str = ""
    from_number: str = ""
    to_number: str = ""
    body: str = ""
    delivery_timestamp: datetime | None = None


@dataclass(frozen=True)
class CallEnded:
    """`agent.call_ended` - call lifecycle ended.

    Payload includes the full transcript and AP-side summary. The post-call
    worker (§C11) consumes this. Unlike live voice turns, `call_ended` does
    carry the real callId, numberId, from/to.
    """

    kind: Literal["call_ended"] = field(default="call_ended", init=False)
    scope: WebhookScope = field(default=None)  # type: ignore[assignment]
    ap_call_id: str = ""
    ap_number_id: str = ""
    ap_agent_id: str = ""
    from_number: str = ""
    to_number: str = ""
    full_transcript: str = ""
    provider_summary: str | None = None
    user_sentiment: str | None = None
    call_successful: bool | None = None
    ended_at: datetime | None = None


@dataclass(frozen=True)
class ReactionReceived:
    """`agent.reaction` - iMessage tapback. Not used in Phase 0; carried through
    for completeness so future handlers can opt in without re-shaping the union.
    """

    kind: Literal["reaction"] = field(default="reaction", init=False)
    scope: WebhookScope = field(default=None)  # type: ignore[assignment]
    ap_conversation_id: str = ""
    reaction_type: str = ""


TelephonyEvent = InboundVoiceTurn | InboundSMS | CallEnded | ReactionReceived
