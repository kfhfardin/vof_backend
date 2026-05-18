"""Shared helper: provision the production workspace + a rep + sales info.

Goes through the same service-layer code paths that real onboarding uses
(WorkspaceProvisioningService.signup → IntakeProcessor.submit_text), with
two targeted DB tweaks for things that don't have a public Phase 0 API:

  - re-stamp `primary_number` to the real production AP number
    (signup auto-provisions a fake/throwaway number)
  - add a FieldEmployee for the known rep
    (Phase 0 has no public roster endpoint; auto-create on first call
     would also work, but we want the FE present before the call)

Used by:
  - tests/integration/test_onboarding_and_intake.py — assertions on each step
  - tests/integration/conftest.py — session finalizer that re-seeds after
    every per-test truncate, so the operator can dial +14783304859
    immediately after the integration suite runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.db.app_session import app_session
from app.db.repositories.field_employees_repo import FieldEmployeesRepo
from app.db.repositories.users_repo import UsersRepo
from app.db.repositories.workspaces_repo import WorkspacesRepo
from app.brain.postgres_brain import PostgresBrainProvider
from app.deps import get_object_store
from app.memory.stub import StubCallerMemoryProvider
from app.services.auth_service import AuthService
from app.services.intake_processor import IntakeProcessor
from app.services.intake_processing import process_intake_item
from app.services.workspace_provisioning import WorkspaceProvisioningService
from app.skills.llm_client import FakeLLMClient
from app.telephony.fake import FakeTelephonyProvider

# --- Production-pinned values (mirror scripts/seed_test_workspace.py) ---
PROD_AP_NUMBER = "+14783304859"
PROD_AP_AGENT_ID = "cmpa4o1e005ecjz00n7khhuzm"  # AP agent that owns +14783304859
PROD_REP_PHONE = "+17653506634"
PROD_REP_NAME = "Production Test Rep"
PROD_MANAGER_EMAIL = "manager@votf-prod.com"
PROD_MANAGER_PASSWORD = "correct horse battery staple"
PROD_WORKSPACE_NAME = "VotF Manager Workspace"

SALES_CAR_INFO = """\
Acme Auto Sales — 2026 Q1 Inventory + Pricing

== Hot Sellers ==
- 2026 Toyota Camry SE: MSRP $28,400, our price $26,900, 7 in stock
- 2026 Honda Accord Sport: MSRP $30,200, our price $28,600, 4 in stock
- 2026 Ford F-150 XLT: MSRP $42,000, our price $39,500, 12 in stock

== Current Promotions (valid through 2026-05-31) ==
- 0% APR for 60 months on Camry + Accord
- $1,500 cashback on F-150
- Trade-in bonus: $1,000 over KBB on any model

== Key Internal Contacts ==
- Service manager: Mike Torres
- Finance: Lisa Chen
- General manager: Sarah Park

== Discounting Policy ==
Sales reps can discount up to 5% without manager approval. Anything above
that requires a decision request to the GM via the orchestrator.
"""


@dataclass(frozen=True)
class OnboardingResult:
    organization_id: UUID
    user_id: UUID
    workspace_id: UUID
    fe_id: UUID
    intake_item_id: UUID
    access_token: str


async def onboard_production_workspace() -> OnboardingResult:
    """Run the full onboarding sequence via real services.

    Idempotent: if the manager / workspace / rep already exist (e.g. the
    session finalizer ran after a prior suite), the helper reuses the
    existing rows instead of erroring on the unique constraints.
    """
    # Skills registry is normally populated by FastAPI lifespan startup;
    # service-level tests bypass that, so load skills (and extractors) up
    # front. Both loaders are idempotent — safe to call repeatedly.
    from app.services import intake_extractors as _intake_extractors  # noqa: F401
    from app.skills import load_all_skills, set_llm_client

    load_all_skills()

    # Inject a deterministic FakeLLMClient so the classifier skill doesn't
    # burn real LLM spend per intake submission. The canned response matches
    # skills/classifier/schema.py:Output for a workspace-wide sales document.
    import json as _json

    set_llm_client(
        FakeLLMClient(
            responses=[
                _json.dumps(
                    {
                        "scope": "ORG_WIDE",
                        "kind": "raw_document",
                        "extracted_entities": [],
                        "confidence": 0.9,
                        "reasoning": "Onboarding sales/inventory document — workspace reference material",
                    }
                ),
            ]
            * 16  # enough for repeat onboarding runs within one test session
        )
    )

    fake_telephony = FakeTelephonyProvider()

    # ---- 1. Signup (creates Org + User + Workspace + Fake AP number) ----
    # Idempotent: if the manager already exists from a prior seed run,
    # fall back to login() to grab fresh tokens for the same user.
    async with app_session() as session:
        existing_user = await UsersRepo(session).get_by_email(PROD_MANAGER_EMAIL)

    if existing_user is None:
        # Pass stubs for memory + brain: ensure_namespace is a no-op for
        # Supermemory containerTags, and PostgresBrainProvider.ensure_schema
        # creates the per-workspace schema — which the brain DB already
        # supports since `make compose-up` brings up the pgvector image.
        memory_stub = StubCallerMemoryProvider()
        brain_provider = PostgresBrainProvider()
        async with app_session() as session:
            svc = WorkspaceProvisioningService(
                session=session,
                telephony=fake_telephony,
                memory=memory_stub,
                brain=brain_provider,
            )
            result = await svc.signup(
                email=PROD_MANAGER_EMAIL,
                password=PROD_MANAGER_PASSWORD,
                workspace_name=PROD_WORKSPACE_NAME,
            )
            organization_id = result.user.organization_id
            user_id = result.user.id
            workspace_id = result.workspace.id
            access_token = result.tokens.access_token
    else:
        async with app_session() as session:
            auth = AuthService(session)
            user, tokens = await auth.login(
                email=PROD_MANAGER_EMAIL, password=PROD_MANAGER_PASSWORD
            )
            assert user.workspace_id is not None, "existing manager must have a workspace"
            organization_id = user.organization_id
            user_id = user.id
            workspace_id = user.workspace_id
            access_token = tokens.access_token

    # ---- 2. Re-stamp the workspace primary_number to the real AP number ----
    async with app_session() as session:
        ws = await WorkspacesRepo(session).get_by_id(workspace_id)
        assert ws is not None
        ws.primary_number = PROD_AP_NUMBER
        ws.agentphone_agent_id = PROD_AP_AGENT_ID
        ws.provisioning_state = "ready"
        await session.commit()

    # ---- 3. Add the known rep (FieldEmployee +17653506634) ----
    async with app_session() as session:
        fes = FieldEmployeesRepo(session)
        existing = await fes.find_by_phone(workspace_id, PROD_REP_PHONE)
        if existing is None:
            fe = await fes.create_unprofiled(
                workspace_id=workspace_id,
                organization_id=organization_id,
                phone=PROD_REP_PHONE,
                provisional_name=PROD_REP_NAME,
            )
            fe.name = PROD_REP_NAME
            fe.role = "AE"
            fe.profiled = True
            await session.commit()
            fe_id = fe.id
        else:
            fe_id = existing.id

    # ---- 4. Submit sales/car info as onboarding intake ----
    storage = get_object_store()
    async with app_session() as session:
        processor = IntakeProcessor(session=session, storage=storage)
        intake_result = await processor.submit_text(
            workspace_id=workspace_id,
            organization_id=organization_id,
            submitted_by_user_id=user_id,
            purpose="onboarding",
            text=SALES_CAR_INFO,
        )
        intake_item_id = intake_result.item.id
        if not intake_result.deduped:
            await process_intake_item(intake_item_id, session=session, storage=storage)
        await session.commit()

    return OnboardingResult(
        organization_id=organization_id,
        user_id=user_id,
        workspace_id=workspace_id,
        fe_id=fe_id,
        intake_item_id=intake_item_id,
        access_token=access_token,
    )
