"""Auth endpoints — signup, login, refresh, logout."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.deps import get_auth_service, get_provisioning_service
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenPair,
    UserSummary,
    WorkspaceSummary,
)
from app.services.auth_service import AuthService
from app.services.workspace_provisioning import WorkspaceProvisioningService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", status_code=status.HTTP_201_CREATED, response_model=SignupResponse)
async def signup(
    body: SignupRequest,
    svc: Annotated[WorkspaceProvisioningService, Depends(get_provisioning_service)],
) -> SignupResponse:
    result = await svc.signup(
        email=body.email,
        password=body.password,
        workspace_name=body.workspace_name,
    )
    return SignupResponse(
        user=UserSummary(
            id=result.user.id,
            email=result.user.email,
            role=result.user.role,
            organization_id=result.user.organization_id,
            workspace_id=result.user.workspace_id,
        ),
        workspace=WorkspaceSummary(
            id=result.workspace.id,
            name=result.workspace.name,
            primary_number=result.workspace.primary_number,
            provisioning_state=result.workspace.provisioning_state,
        ),
        tokens=TokenPair(
            access_token=result.tokens.access_token,
            refresh_token=result.tokens.refresh_token,
            expires_in=result.tokens.expires_in,
        ),
    )


@router.post("/login", response_model=TokenPair)
async def login(
    body: LoginRequest,
    svc: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenPair:
    _user, tokens = await svc.login(email=body.email, password=body.password)
    return TokenPair(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: RefreshRequest,
    svc: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenPair:
    tokens = await svc.refresh(body.refresh_token)
    return TokenPair(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    svc: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    await svc.logout(body.refresh_token)
