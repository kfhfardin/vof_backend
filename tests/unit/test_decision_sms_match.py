"""DecisionService.match_sms_response - pure-logic prefix parsing tests.

The full DB+respond round-trip lives in tests/integration. Here we verify
the body-parsing path against the SAME service that respond() uses,
but with the DB call short-circuited via a fake repo.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.db.models import DecisionRequest
from app.services.decisions import DecisionService, _short_id


class _FakeRepo:
    def __init__(self, decisions: list[DecisionRequest]) -> None:
        self.decisions = decisions
        self.answered: list[DecisionRequest] = []

    async def list_open_for_user(self, user_id):  # type: ignore[no-untyped-def]
        return list(self.decisions)

    async def lock_for_update(self, decision_id):  # type: ignore[no-untyped-def]
        return next((d for d in self.decisions if d.id == decision_id), None)

    async def mark_answered(self, decision, *, response, responded_by_user_id, via, responded_at):  # type: ignore[no-untyped-def]
        decision.status = "answered"
        decision.response = response
        decision.responded_by_user_id = responded_by_user_id
        decision.responded_via = via
        decision.responded_at = responded_at
        self.answered.append(decision)
        return decision


def _make_decision() -> DecisionRequest:
    d = DecisionRequest()
    d.id = uuid4()
    d.call_id = uuid4()
    d.workspace_id = uuid4()
    d.target_user_id = uuid4()
    d.prompt = "approve 10% discount?"
    d.options = ["Approve 10%", "Hold firm"]
    d.decision_class = "inline"
    d.timeout_at = datetime.now(UTC)
    d.status = "open"
    return d


class _FakeSession:
    async def commit(self) -> None:
        pass


class _ServiceUnderTest(DecisionService):
    """DecisionService variant that skips DB commit + WS publish."""

    def __init__(self, fake_repo) -> None:  # type: ignore[no-untyped-def]
        self.repo = fake_repo  # type: ignore[assignment]
        self._telephony = None
        self.session = _FakeSession()  # type: ignore[assignment]

    async def _publish_resolved(self, decision):  # type: ignore[no-untyped-def]
        pass


async def test_match_sms_no_prefix_returns_none() -> None:
    svc = _ServiceUnderTest(_FakeRepo([]))
    assert await svc.match_sms_response(body="just chatter", manager_user_id=uuid4()) is None


async def test_match_sms_unknown_short_id_returns_none() -> None:
    svc = _ServiceUnderTest(_FakeRepo([_make_decision()]))
    body = "[DR-ABCDEF] Approve 10%"
    assert await svc.match_sms_response(body=body, manager_user_id=uuid4()) is None


async def test_match_sms_resolves_to_decision() -> None:
    d = _make_decision()
    repo = _FakeRepo([d])
    svc = _ServiceUnderTest(repo)
    body = f"[DR-{_short_id(d.id)}] Approve 10%"
    result = await svc.match_sms_response(body=body, manager_user_id=d.target_user_id)
    assert result is not None
    assert result.id == d.id
    assert result.status == "answered"
    assert result.response == "Approve 10%"
    assert result.responded_via == "sms"


async def test_match_sms_case_insensitive_option() -> None:
    d = _make_decision()
    repo = _FakeRepo([d])
    svc = _ServiceUnderTest(repo)
    body = f"[DR-{_short_id(d.id)}] approve 10%"  # lower-case
    result = await svc.match_sms_response(body=body, manager_user_id=d.target_user_id)
    assert result is not None and result.response == "Approve 10%"


async def test_match_sms_unrecognized_option_returns_row_unanswered() -> None:
    d = _make_decision()
    repo = _FakeRepo([d])
    svc = _ServiceUnderTest(repo)
    body = f"[DR-{_short_id(d.id)}] maybe"
    result = await svc.match_sms_response(body=body, manager_user_id=d.target_user_id)
    assert result is not None and result.id == d.id
    # Status stays open - caller decides how to nudge the Manager.
    assert result.status == "open"


@pytest.mark.parametrize("malformed", ["[DR-]", "[DR-X", "[DR- ]Yes"])
async def test_match_sms_malformed_returns_none(malformed: str) -> None:
    svc = _ServiceUnderTest(_FakeRepo([]))
    assert await svc.match_sms_response(body=malformed, manager_user_id=uuid4()) is None
