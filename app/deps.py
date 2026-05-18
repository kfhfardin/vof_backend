"""Shared FastAPI dependencies."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends, HTTPException, Path, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.base import BrainProvider
from app.brain.postgres_brain import PostgresBrainProvider
from app.db.app_session import app_session
from app.db.models import User
from app.db.repositories.users_repo import UsersRepo
from app.errors import Forbidden
from app.memory.base import CallerMemoryProvider
from app.memory.stub import StubCallerMemoryProvider
from app.security.jwt import InvalidToken, decode_token
from app.services.auth_service import AuthService
from app.services.intake_processor import IntakeProcessor
from app.services.workspace_provisioning import WorkspaceProvisioningService
from app.settings import get_settings
from app.storage.base import ObjectStore
from app.storage.s3 import S3ObjectStore
from app.telephony.agentphone import AgentPhoneAdapter
from app.telephony.base import TelephonyProvider
from app.telephony.fake import FakeTelephonyProvider

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


# ---------------- Session ----------------


async def get_session() -> AsyncIterator[AsyncSession]:
    async with app_session() as session:
        yield session


# ---------------- Provider singletons ----------------
#
# Real implementations are bound on first access. Tests override via FastAPI
# `app.dependency_overrides[get_telephony_provider] = lambda: fake` rather
# than mutating these globals.

_telephony: TelephonyProvider | None = None
_memory: CallerMemoryProvider | None = None
_brain: BrainProvider | None = None
_object_store: ObjectStore | None = None


def _build_telephony() -> TelephonyProvider:
    """Real AgentPhoneAdapter if AGENTPHONE_API_KEY is set; FakeTelephonyProvider otherwise.

    Empty-key path prints a warning so dev environments without an AP account
    don't silently get fake numbers in places that look real.
    """
    settings = get_settings()
    key = settings.agentphone_api_key.get_secret_value()
    if key:
        return AgentPhoneAdapter(api_key=key)
    import sys

    sys.stderr.write(
        "WARNING: AGENTPHONE_API_KEY not set; using FakeTelephonyProvider. "
        "Signup will produce fake phone numbers. Set the key in .env.local for "
        "real AP integration.\n"
    )
    return FakeTelephonyProvider()


def get_telephony_provider() -> TelephonyProvider:
    global _telephony
    if _telephony is None:
        _telephony = _build_telephony()
    return _telephony


def _build_memory() -> CallerMemoryProvider:
    """Real SupermemoryCallerMemoryProvider if SUPERMEMORY_API_KEY is set;
    StubCallerMemoryProvider otherwise. Empty-key path warns to stderr."""
    settings = get_settings()
    key = settings.supermemory_api_key.get_secret_value()
    if key:
        from app.memory.supermemory import SupermemoryCallerMemoryProvider

        return SupermemoryCallerMemoryProvider(api_key=key)
    import sys

    sys.stderr.write(
        "WARNING: SUPERMEMORY_API_KEY not set; using StubCallerMemoryProvider. "
        "Per-call caller-memory writes will no-op. Set the key in .env.local for "
        "real Supermemory integration.\n"
    )
    return StubCallerMemoryProvider()


def get_memory_provider() -> CallerMemoryProvider:
    global _memory
    if _memory is None:
        _memory = _build_memory()
    return _memory


def get_brain_provider() -> BrainProvider:
    global _brain
    if _brain is None:
        _brain = PostgresBrainProvider()
    return _brain


def get_object_store() -> ObjectStore:
    global _object_store
    if _object_store is None:
        _object_store = S3ObjectStore()
    return _object_store


# ---------------- Services ----------------


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthService:
    return AuthService(session)


def get_provisioning_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    telephony: Annotated[TelephonyProvider, Depends(get_telephony_provider)],
    memory: Annotated[CallerMemoryProvider, Depends(get_memory_provider)],
    brain: Annotated[BrainProvider, Depends(get_brain_provider)],
) -> WorkspaceProvisioningService:
    return WorkspaceProvisioningService(session, telephony, memory, brain)


def get_intake_processor(
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[ObjectStore, Depends(get_object_store)],
) -> IntakeProcessor:
    return IntakeProcessor(session, storage)


# ---------------- Auth dependencies ----------------


async def current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if not token:
        raise HTTPException(status_code=401, detail="unauthenticated")
    try:
        payload = decode_token(token, expected_type="access")
    except InvalidToken as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    repo = UsersRepo(session)
    user = await repo.get_by_id(UUID(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")

    # Bind log context for the rest of this request
    structlog.contextvars.bind_contextvars(
        user_id=str(user.id),
        workspace_id=str(user.workspace_id) if user.workspace_id else None,
        role=user.role,
    )
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_workspace_access(
    workspace_id: Annotated[UUID, Path(...)],
    user: CurrentUser,
) -> User:
    if user.workspace_id is None or str(user.workspace_id) != str(workspace_id):
        raise Forbidden("wrong_workspace_scope")
    if user.role != "manager":  # Phase 0: only manager exposed
        raise Forbidden("insufficient_role")
    return user


def require_org_access(
    organization_id: Annotated[UUID, Path(...)],
    user: CurrentUser,
) -> User:
    if user.role != "org_admin" or str(user.organization_id) != str(organization_id):
        raise Forbidden("org_admin_only")
    return user


def require_rep_access(user: CurrentUser) -> User:
    if user.role != "rep":
        raise Forbidden("rep_only")
    return user
