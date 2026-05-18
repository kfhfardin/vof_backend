"""Orchestrator prompt rendering - templates produce expected sections."""

import uuid
from datetime import UTC, datetime

from app.brain.base import BrainSearchHit
from app.memory.base import CallerMemoryHit, CallerProfile
from app.orchestrator.prompts import render_messages
from app.orchestrator.retrieval import RetrievedContext
from app.orchestrator.session import CallSession


class _FakeWorkspace:
    def __init__(self, name: str) -> None:
        self.name = name
        self.id = uuid.uuid4()


class _FakeFE:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.name = "Sarah Chen"
        self.role = "AE"
        self.team = "West"
        self.profiled = True
        self.profile = {"strengths": ["discovery"]}


def test_render_includes_caller_block_and_utterance() -> None:
    ws = _FakeWorkspace("Acme Sales")
    fe = _FakeFE()
    sess = CallSession(call_id=uuid.uuid4(), workspace_id=ws.id, field_employee_id=fe.id)
    sess.append_turn(speaker="caller", text="prior turn", ts=datetime.now(UTC))
    ctx = RetrievedContext(
        caller_hits=[
            CallerMemoryHit(
                id="m1",
                content="Sarah usually opens with discovery questions",
                score=0.9,
                metadata={"title": "style"},
            )
        ],
        brain_hits=[
            BrainSearchHit(slug="accounts/acme", title="Acme Corp", snippet="renewing Q3", score=0.7),
        ],
        caller_profile=CallerProfile(container_tag="caller_u", summary="experienced AE", facts={}),
    )
    msgs = render_messages(
        workspace=ws,  # type: ignore[arg-type]
        field_employee=fe,  # type: ignore[arg-type]
        session=sess,
        context=ctx,
        rep_utterance="I just met with the Acme buyer.",
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    user = msgs[1]["content"]
    assert "Sarah Chen" in user
    assert "experienced AE" in user
    assert "discovery questions" in user
    assert "accounts/acme" in user
    assert "Acme buyer" in user
    assert "prior turn" in user


def test_render_handles_unprofiled_caller_and_empty_context() -> None:
    ws = _FakeWorkspace("Acme")
    sess = CallSession(call_id=uuid.uuid4(), workspace_id=ws.id, field_employee_id=None)
    msgs = render_messages(
        workspace=ws,  # type: ignore[arg-type]
        field_employee=None,
        session=sess,
        context=RetrievedContext(),
        rep_utterance="hi",
    )
    user = msgs[1]["content"]
    assert "(unprofiled)" in user
    # No retrieved-context sections rendered when both lists are empty.
    assert "## Caller memory" not in user
    assert "## Workspace brain" not in user


def test_render_includes_manager_whispers_when_present() -> None:
    ws = _FakeWorkspace("Acme")
    fe = _FakeFE()
    sess = CallSession(call_id=uuid.uuid4(), workspace_id=ws.id, field_employee_id=fe.id)
    sess.manager_whispers = ["Push on the integration timeline."]
    msgs = render_messages(
        workspace=ws,  # type: ignore[arg-type]
        field_employee=fe,  # type: ignore[arg-type]
        session=sess,
        context=RetrievedContext(),
        rep_utterance="anything else?",
    )
    user = msgs[1]["content"]
    assert "Manager guidance" in user
    assert "integration timeline" in user


def test_render_includes_answered_decision_update() -> None:
    from app.orchestrator.prompts import DecisionUpdate

    ws = _FakeWorkspace("Acme")
    fe = _FakeFE()
    sess = CallSession(call_id=uuid.uuid4(), workspace_id=ws.id, field_employee_id=fe.id)
    update = DecisionUpdate(
        decision_id="abc",
        prompt="approve 10% discount?",
        status="answered",
        response="Approve 10%",
        via="websocket",
    )
    msgs = render_messages(
        workspace=ws,  # type: ignore[arg-type]
        field_employee=fe,  # type: ignore[arg-type]
        session=sess,
        context=RetrievedContext(),
        rep_utterance="anything else?",
        decision_updates=[update],
    )
    user = msgs[1]["content"]
    assert "Pending decisions resolved" in user
    assert "Approve 10%" in user
    assert "approve 10% discount?" in user


def test_render_includes_timed_out_decision_instructs_to_move_on() -> None:
    from app.orchestrator.prompts import DecisionUpdate

    ws = _FakeWorkspace("Acme")
    fe = _FakeFE()
    sess = CallSession(call_id=uuid.uuid4(), workspace_id=ws.id, field_employee_id=fe.id)
    update = DecisionUpdate(
        decision_id="abc",
        prompt="approve 10% discount?",
        status="timed_out",
        response=None,
        via="timeout",
    )
    msgs = render_messages(
        workspace=ws,  # type: ignore[arg-type]
        field_employee=fe,  # type: ignore[arg-type]
        session=sess,
        context=RetrievedContext(),
        rep_utterance="anything else?",
        decision_updates=[update],
    )
    user = msgs[1]["content"]
    assert "did not respond" in user
    assert "move on" in user
