"""Decision timeout worker - logic-only unit tests.

The full Redis-backed schedule + fire round-trip lives in tests/integration.
Here we verify:
  - the timeout-mode short-circuit (DECISION_TIMEOUT_INLINE)
  - job_id derivation
  - the next-turn prompt picks up resolved/timed-out decisions
"""

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from app.db.models import DecisionRequest
from app.orchestrator.prompts import (
    DecisionUpdate,
    decision_updates_from_rows,
)
from app.workers.decision_timeout import _is_test_mode, job_id, schedule_or_inline


def test_job_id_is_decision_id_prefixed() -> None:
    did = uuid4()
    assert job_id(did) == f"dt:{did}"


def test_test_mode_toggle_via_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("DECISION_TIMEOUT_INLINE", raising=False)
    assert _is_test_mode() is False
    monkeypatch.setenv("DECISION_TIMEOUT_INLINE", "1")
    assert _is_test_mode() is True


async def test_schedule_or_inline_skips_redis_in_test_mode(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DECISION_TIMEOUT_INLINE", "1")
    with patch("app.workers.decision_timeout.create_pool") as cp:
        await schedule_or_inline(uuid4(), datetime.now(UTC))
        cp.assert_not_called()


def _make_decision(status: str, response: str | None = None, via: str | None = None) -> DecisionRequest:
    d = DecisionRequest()
    d.id = uuid4()
    d.call_id = uuid4()
    d.workspace_id = uuid4()
    d.target_user_id = uuid4()
    d.prompt = "approve 10% discount?"
    d.options = ["Approve 10%", "Hold firm"]
    d.decision_class = "inline"
    d.status = status  # type: ignore[assignment]
    d.response = response
    d.responded_via = via  # type: ignore[assignment]
    return d


def test_decision_updates_from_rows_picks_resolved_only() -> None:
    rows = [
        _make_decision("open"),
        _make_decision("answered", response="Approve 10%", via="websocket"),
        _make_decision("timed_out", via="timeout"),
        _make_decision("cancelled"),
    ]
    updates = decision_updates_from_rows(rows)
    statuses = sorted(u.status for u in updates)
    assert statuses == ["answered", "timed_out"]
    answered = next(u for u in updates if u.status == "answered")
    assert answered.response == "Approve 10%"
    assert answered.via == "websocket"
    timed = next(u for u in updates if u.status == "timed_out")
    assert timed.response is None
    assert timed.via == "timeout"


def test_decision_updates_empty_when_all_open() -> None:
    assert decision_updates_from_rows([_make_decision("open"), _make_decision("open")]) == []


def test_decision_update_is_immutable_dataclass() -> None:
    import dataclasses

    import pytest

    u = DecisionUpdate(decision_id="x", prompt="p", status="answered", response="y", via="websocket")
    with pytest.raises(dataclasses.FrozenInstanceError):
        u.response = "tampered"  # type: ignore[misc]
