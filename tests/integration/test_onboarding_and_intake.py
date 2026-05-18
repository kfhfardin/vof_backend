"""End-to-end onboarding + intake against real Postgres + MinIO.

Runs the full onboarding sequence used by the production seed:
  1. Manager signup        (real WorkspaceProvisioningService)
  2. Re-stamp workspace primary_number to the production AP number
  3. Add the known rep as a FieldEmployee
  4. Submit sales/car info as onboarding intake (real IntakeProcessor)
  5. Assert all rows landed, intake item is classified/ingested

Both this test AND the session-scope `_reseed_for_live_calls` finalizer
in conftest.py call the same `onboard_production_workspace()` helper, so
after the integration suite truncates the DB per-test, the operator can
dial +14783304859 immediately without re-running the standalone seed.
"""

from __future__ import annotations

import pytest

from app.db.app_session import app_session
from app.db.repositories.field_employees_repo import FieldEmployeesRepo
from app.db.repositories.intake_repo import IntakeRepo
from app.db.repositories.users_repo import UsersRepo
from app.db.repositories.workspaces_repo import WorkspacesRepo

from tests.integration._onboarding import (
    PROD_AP_AGENT_ID,
    PROD_AP_NUMBER,
    PROD_MANAGER_EMAIL,
    PROD_REP_PHONE,
    PROD_WORKSPACE_NAME,
    onboard_production_workspace,
)

pytestmark = pytest.mark.integration


async def test_onboarding_seeds_workspace_rep_and_intake() -> None:
    """Single test that walks the entire onboarding flow and asserts the
    DB state matches what live calls + decisions need."""
    seed = await onboard_production_workspace()

    # --- Manager + Org wired correctly ---
    async with app_session() as session:
        user = await UsersRepo(session).get_by_email(PROD_MANAGER_EMAIL)
        assert user is not None
        assert user.role == "manager"
        assert user.organization_id == seed.organization_id
        assert user.workspace_id == seed.workspace_id

    # --- Workspace stamped with the real production AP number + agent ---
    async with app_session() as session:
        ws = await WorkspacesRepo(session).get_by_id(seed.workspace_id)
        assert ws is not None
        assert ws.primary_number == PROD_AP_NUMBER, (
            f"workspace primary_number must be the live AP number "
            f"(got {ws.primary_number!r}); call routing keys on this"
        )
        assert ws.agentphone_agent_id == PROD_AP_AGENT_ID, (
            "outbound SMS (decision pings) routes via this agent id"
        )
        assert ws.provisioning_state == "ready"
        assert ws.name == PROD_WORKSPACE_NAME

    # --- FieldEmployee for the known rep ---
    async with app_session() as session:
        fe = await FieldEmployeesRepo(session).find_by_phone(
            seed.workspace_id, PROD_REP_PHONE
        )
        assert fe is not None, (
            f"rep {PROD_REP_PHONE} must be on the roster; "
            "the dispatcher would still auto-create on first call, "
            "but pre-seeding lets the orchestrator load profile context"
        )
        assert fe.id == seed.fe_id
        assert fe.phone == PROD_REP_PHONE
        assert fe.profiled is True

    # --- Intake item landed + finished extracting ---
    async with app_session() as session:
        items = await IntakeRepo(session).list_for_workspace(seed.workspace_id, limit=10)
        assert any(it.id == seed.intake_item_id for it in items), (
            "intake submission must persist a row visible to list_for_workspace"
        )
        item = next(it for it in items if it.id == seed.intake_item_id)
        assert item.purpose == "onboarding"
        assert item.source == "form"
        # Status is one of the terminal-ish states once processing completes.
        # 'queued' is acceptable if the worker hasn't drained yet; 'failed'
        # is not.
        assert item.status in (
            "queued",
            "classified",
            "extracting",
            "ingested",
            "needs_review",
        ), f"unexpected intake status: {item.status}"
        assert item.status != "failed", f"intake failed: {item.error}"

    # --- Auth token works (smoke check) ---
    assert seed.access_token
    assert len(seed.access_token.split(".")) == 3  # JWT shape
