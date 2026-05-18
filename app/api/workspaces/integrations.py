"""Workspace integrations REST API (F9: Google Workspace OAuth surface).

  GET    /workspaces/{wid}/integrations/google/auth_url
  GET    /workspaces/{wid}/integrations/google/callback?code=...&state=...
  GET    /workspaces/{wid}/integrations
  DELETE /workspaces/{wid}/integrations/{integration_id}

The auth_url endpoint returns a JSON envelope `{auth_url: str}` rather
than a 302 so the FE owns the redirect. The callback responds with
JSON `{status: "connected", ...}` for now; FE polls `/integrations`
after redirect to update its panel.

No tokens are ever returned by these endpoints - the response shape is
the public dict from `OAuthCredentialsRepo.to_public()`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.google_workspace import (
    GoogleWorkspaceConnector,
    GoogleWorkspaceNotConfigured,
    decode_state,
    is_google_workspace_configured,
)
from app.db.repositories.oauth_credentials_repo import OAuthCredentialsRepo
from app.deps import CurrentUser, get_session, require_workspace_access
from app.errors import Forbidden, NotFound, Validation
from app.logging import get_logger
from app.settings import get_settings

log = get_logger(__name__)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/integrations",
    tags=["integrations"],
)


def _callback_redirect_uri(workspace_id: UUID) -> str:
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    return f"{base}/api/v1/workspaces/{workspace_id}/integrations/google/callback"


_GOOGLE_DISABLED_DETAIL = {
    "error": "google_oauth_not_configured",
    "message": (
        "Google Workspace integration is optional and disabled in this "
        "deployment. Set GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET "
        "to enable Gmail send + Calendar events handlers."
    ),
}


def _require_google_configured() -> None:
    if not is_google_workspace_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_GOOGLE_DISABLED_DETAIL,
        )


@router.get(
    "/google/auth_url",
    dependencies=[Depends(require_workspace_access)],
)
async def google_auth_url(
    workspace_id: UUID,
    user: CurrentUser,
) -> dict[str, str]:
    _require_google_configured()
    connector = GoogleWorkspaceConnector()
    url = await connector.build_auth_url(
        workspace_id=workspace_id,
        user_id=user.id,
        redirect_uri=_callback_redirect_uri(workspace_id),
    )
    return {"auth_url": url}


@router.get(
    "/google/callback",
    dependencies=[Depends(require_workspace_access)],
)
async def google_callback(
    workspace_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    code: Annotated[str, Query(...)],
    state: Annotated[str, Query(...)],
) -> dict[str, object]:
    """OAuth callback - exchanges `code` for tokens and persists.

    `state` is validated against (workspace_id, authenticated user) before
    we exchange the code so a stolen code can't be redeemed against a
    different workspace.
    """
    try:
        state_wid, state_uid = decode_state(state)
    except Exception as e:  # noqa: BLE001
        raise Validation("invalid state parameter") from e

    if state_wid != workspace_id or state_uid != user.id:
        raise Forbidden("state mismatch")

    _require_google_configured()
    connector = GoogleWorkspaceConnector()
    creds = await connector.handle_callback(
        workspace_id=workspace_id,
        user_id=user.id,
        code=code,
        redirect_uri=_callback_redirect_uri(workspace_id),
    )

    repo = OAuthCredentialsRepo(session)
    payload = repo.to_public(creds)
    return {"status": "connected", "integration": payload}


@router.get(
    "",
    dependencies=[Depends(require_workspace_access)],
)
async def list_integrations(
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, list[dict[str, object]]]:
    repo = OAuthCredentialsRepo(session)
    rows = await repo.list_all_for_workspace(workspace_id)
    return {"integrations": [repo.to_public(r) for r in rows]}


@router.delete(
    "/{integration_id}",
    status_code=204,
    dependencies=[Depends(require_workspace_access)],
)
async def disconnect_integration(
    workspace_id: UUID,
    integration_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    repo = OAuthCredentialsRepo(session)
    creds = await repo.get(integration_id)
    if creds is None or creds.workspace_id != workspace_id:
        raise NotFound("integration not found")
    if not creds.revoked:
        await repo.mark_revoked(creds, revoked_at=datetime.now(UTC))
        await session.commit()
