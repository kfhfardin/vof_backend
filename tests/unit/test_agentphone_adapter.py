"""AgentPhone adapter unit tests.

Webhook parse_webhook is the load-bearing pure-function we care about:
given a raw body + headers, does it produce the right TelephonyEvent
subtype with the right fields? REST methods (provision_number, send_sms,
set_conversation_state) are network-bound and exercised via the smoke
probe + integration tests.
"""

import json

import pytest

from app.telephony.agentphone import AgentPhoneAdapter
from app.telephony.events import (
    CallEnded,
    InboundSMS,
    InboundVoiceTurn,
    ReactionReceived,
)


def _adapter() -> AgentPhoneAdapter:
    return AgentPhoneAdapter(api_key="sk-test-only")


def test_constructor_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="non-empty API key"):
        AgentPhoneAdapter(api_key="")


def test_parse_voice_turn_uses_conversation_state_scope() -> None:
    body = json.dumps(
        {
            "event": "agent.message",
            "channel": "voice",
            "timestamp": "2026-05-17T14:00:05Z",
            "agentId": "agt_abc",
            "data": {
                "callId": "call_xyz",
                "numberId": "num_xyz",
                "from": "+15559876543",
                "to": "+15551234567",
                "transcript": "I just met with Acme",
                "confidence": 0.95,
                "direction": "inbound",
            },
            "conversationState": {
                "workspace_id": "11111111-1111-1111-1111-111111111111",
                "field_employee_id": "22222222-2222-2222-2222-222222222222",
                "call_id": "33333333-3333-3333-3333-333333333333",
            },
        }
    ).encode()
    ev = _adapter().parse_webhook(body, headers={})
    assert isinstance(ev, InboundVoiceTurn)
    assert ev.transcript == "I just met with Acme"
    assert ev.ap_call_id == "call_xyz"
    assert ev.from_number == "+15559876543"
    assert ev.confidence == 0.95
    assert str(ev.scope.workspace_id) == "11111111-1111-1111-1111-111111111111"
    assert str(ev.scope.field_employee_id) == "22222222-2222-2222-2222-222222222222"


def test_parse_voice_turn_without_scope_yields_sentinel_workspace() -> None:
    body = json.dumps(
        {
            "event": "agent.message",
            "channel": "voice",
            "data": {"callId": "call_x", "from": "+1", "to": "+2", "transcript": "hi"},
        }
    ).encode()
    ev = _adapter().parse_webhook(body, headers={})
    assert isinstance(ev, InboundVoiceTurn)
    # Sentinel UUID -> the webhook endpoint will fall back to DB lookup
    assert ev.scope.workspace_id.int == 0


def test_parse_inbound_sms() -> None:
    body = json.dumps(
        {
            "event": "agent.message",
            "channel": "sms",
            "data": {
                "conversationId": "conv_1",
                "from": "+15559876543",
                "to": "+15551234567",
                "body": "Sarah just left a customer",
            },
        }
    ).encode()
    ev = _adapter().parse_webhook(body, headers={})
    assert isinstance(ev, InboundSMS)
    assert ev.channel == "sms"
    assert ev.body == "Sarah just left a customer"
    assert ev.ap_conversation_id == "conv_1"


def test_parse_inbound_imessage() -> None:
    body = json.dumps({"event": "agent.message", "channel": "imessage", "data": {"text": "yes"}}).encode()
    ev = _adapter().parse_webhook(body, headers={})
    assert isinstance(ev, InboundSMS)
    assert ev.channel == "imessage"
    assert ev.body == "yes"


def test_parse_call_ended() -> None:
    body = json.dumps(
        {
            "event": "agent.call_ended",
            "channel": "voice",
            "timestamp": "2026-05-17T14:30:00Z",
            "data": {
                "callId": "call_xyz",
                "transcript": "full transcript here",
                "summary": "discussed pricing",
                "userSentiment": "positive",
                "callSuccessful": True,
            },
        }
    ).encode()
    ev = _adapter().parse_webhook(body, headers={})
    assert isinstance(ev, CallEnded)
    assert ev.ap_call_id == "call_xyz"
    assert ev.provider_summary == "discussed pricing"
    assert ev.user_sentiment == "positive"
    assert ev.call_successful is True


def test_parse_reaction() -> None:
    body = json.dumps(
        {
            "event": "agent.reaction",
            "channel": "imessage",
            "data": {"conversationId": "c", "reaction": "love"},
        }
    ).encode()
    ev = _adapter().parse_webhook(body, headers={})
    assert isinstance(ev, ReactionReceived)
    assert ev.reaction_type == "love"


def test_parse_unknown_event_raises() -> None:
    from app.errors import UpstreamError

    body = json.dumps({"event": "agent.something_new", "channel": "voice", "data": {}}).encode()
    with pytest.raises(UpstreamError, match="unknown AgentPhone event"):
        _adapter().parse_webhook(body, headers={})


def test_parse_invalid_json_raises() -> None:
    from app.errors import UpstreamError

    with pytest.raises(UpstreamError, match="not JSON"):
        _adapter().parse_webhook(b"not json", headers={})
