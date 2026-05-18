"""CallSession serialization + history cap.

Redis-backed save/load is exercised in integration tests.
"""

from datetime import UTC, datetime
from uuid import uuid4

from app.orchestrator.session import HISTORY_CAP, CallSession


def test_round_trips_via_json() -> None:
    sess = CallSession(
        call_id=uuid4(),
        workspace_id=uuid4(),
        field_employee_id=uuid4(),
        state_version=3,
    )
    sess.append_turn(speaker="caller", text="hi", ts=datetime.now(UTC))
    sess.append_turn(speaker="agent", text="hello", ts=datetime.now(UTC))

    raw = sess.to_json()
    sess2 = CallSession.from_json(raw)
    assert sess2.call_id == sess.call_id
    assert sess2.workspace_id == sess.workspace_id
    assert sess2.field_employee_id == sess.field_employee_id
    assert sess2.state_version == 3
    assert [t.text for t in sess2.conversation_history] == ["hi", "hello"]


def test_history_caps_at_hard_limit() -> None:
    sess = CallSession(call_id=uuid4(), workspace_id=uuid4(), field_employee_id=None)
    for i in range(HISTORY_CAP + 10):
        sess.append_turn(speaker="caller", text=f"t{i}", ts=datetime.now(UTC))
    assert len(sess.conversation_history) == HISTORY_CAP
    # We kept the most recent turns
    assert sess.conversation_history[-1].text == f"t{HISTORY_CAP + 9}"


def test_empty_session_has_zero_history_and_version() -> None:
    sess = CallSession(call_id=uuid4(), workspace_id=uuid4(), field_employee_id=None)
    assert sess.state_version == 0
    assert sess.conversation_history == []
    assert sess.pending_decisions == []
    assert sess.manager_whispers == []
