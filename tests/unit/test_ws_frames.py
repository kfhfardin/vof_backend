"""WS frame schemas - discriminator + round-trip."""

import json
from datetime import UTC, datetime
from uuid import uuid4

from app.schemas.ws_frames import (
    CallEndedFrame,
    CallStartedFrame,
    DecisionOpenedFrame,
    DecisionResolvedFrame,
    SnapshotFrame,
    TranscriptFragmentFrame,
)


def test_call_started_frame_round_trips_as_json() -> None:
    frame = CallStartedFrame(call_id=uuid4(), field_employee_id=uuid4(), started_at=datetime.now(UTC))
    payload = frame.model_dump(mode="json")
    assert payload["type"] == "call.started"
    # Re-parse
    parsed = CallStartedFrame.model_validate(payload)
    assert parsed.call_id == frame.call_id


def test_transcript_fragment_frame_carries_seq_and_speaker() -> None:
    frame = TranscriptFragmentFrame(
        call_id=uuid4(),
        speaker="caller",
        text="hello",
        seq=3,
        ts=datetime.now(UTC),
    )
    payload = frame.model_dump(mode="json")
    assert payload["type"] == "transcript.fragment"
    assert payload["seq"] == 3
    assert payload["speaker"] == "caller"


def test_decision_opened_and_resolved_frame_shapes() -> None:
    opened = DecisionOpenedFrame(
        call_id=uuid4(),
        decision_id=uuid4(),
        prompt="approve discount?",
        options=["yes", "no"],
        decision_class="inline",
        timeout_at=datetime.now(UTC),
    )
    assert opened.type == "decision.opened"
    resolved = DecisionResolvedFrame(
        call_id=uuid4(),
        decision_id=uuid4(),
        response="yes",
        responded_via="websocket",
    )
    assert resolved.type == "decision.resolved"


def test_call_ended_frame_shape() -> None:
    frame = CallEndedFrame(call_id=uuid4(), ended_at=datetime.now(UTC))
    payload = frame.model_dump(mode="json")
    assert payload["type"] == "call.ended"


def test_snapshot_frame_contains_call_started_entries() -> None:
    snap = SnapshotFrame(
        calls=[CallStartedFrame(call_id=uuid4(), field_employee_id=None, started_at=datetime.now(UTC))]
    )
    payload = json.loads(json.dumps(snap.model_dump(mode="json"), default=str))
    assert payload["type"] == "snapshot"
    assert len(payload["calls"]) == 1
    assert payload["calls"][0]["type"] == "call.started"
