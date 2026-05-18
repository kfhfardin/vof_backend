"""Connector helpers shared across vendor adapters.

Centralized token-refresh path: any caller about to issue a provider API
request asks `refresh_if_needed(workspace_id, provider)` first. This
keeps the refresh -> store-back-to-DB -> set Authorization header cycle
in one place so a vendor adding a new auth quirk only touches its own
adapter.

`OAuthRevokedError` is raised when a provider returns invalid_grant on
refresh. Callers convert this into `needs_reconnect` on the surface
they're presenting (ActionItem status, FE settings page, etc.).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.db.app_session import app_session
from app.db.models import OAuthProvider, WorkspaceOAuthCredentials
from app.db.repositories.oauth_credentials_repo import OAuthCredentialsRepo
from app.logging import get_logger

log = get_logger(__name__)

# Conservative skew: if the access token expires within this window, force a refresh.
_REFRESH_SKEW = timedelta(seconds=120)


class OAuthRevokedError(Exception):
    """Raised when the provider has revoked the refresh token.

    Caller should `mark_revoked()` on the credential row and surface
    `needs_reconnect` to the FE.
    """

    def __init__(self, provider: str, integration_id: UUID | None, detail: str = "") -> None:
        super().__init__(f"{provider} OAuth revoked (integration={integration_id}): {detail}")
        self.provider = provider
        self.integration_id = integration_id
        self.detail = detail


def _is_access_token_fresh(creds: WorkspaceOAuthCredentials) -> bool:
    if not creds.access_token:
        return False
    if creds.access_token_expires_at is None:
        return False
    return creds.access_token_expires_at - _REFRESH_SKEW > datetime.now(UTC)


async def refresh_if_needed(
    workspace_id: UUID, provider: OAuthProvider
) -> WorkspaceOAuthCredentials | None:
    """Return active credentials with a fresh access_token, or None if none exist.

    Raises `OAuthRevokedError` if the refresh attempt is rejected by the
    provider; the credential row is marked `revoked=True` before raising.
    """
    async with app_session() as session:
        repo = OAuthCredentialsRepo(session)
        creds = await repo.get_active(workspace_id, provider)
        if creds is None:
            return None
        if _is_access_token_fresh(creds):
            return creds

        # Refresh inline. Import here to avoid a connectors-base ↔ vendor cycle.
        if provider == "google_workspace":
            from app.connectors.google_workspace import GoogleWorkspaceConnector

            try:
                refreshed = await GoogleWorkspaceConnector().refresh_access_token(creds)
            except OAuthRevokedError:
                await repo.mark_revoked(creds, revoked_at=datetime.now(UTC))
                await session.commit()
                raise
            await repo.update_tokens(
                creds,
                access_token=refreshed.access_token,
                access_token_expires_at=refreshed.access_token_expires_at,
                refresh_token=refreshed.refresh_token,
            )
            await session.commit()
            return refreshed
        # Future providers wire in here.
        raise ValueError(f"unknown provider {provider!r}")
