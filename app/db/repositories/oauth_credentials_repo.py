"""WorkspaceOAuthCredentials repository.

Caller convention: `get_active(workspace_id, provider)` returns the
most-recent non-revoked credential row. `mark_revoked` is one-way -
to reconnect, callers create a fresh row via `create()`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OAuthProvider, WorkspaceOAuthCredentials


class OAuthCredentialsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        workspace_id: UUID,
        provider: OAuthProvider,
        scopes: list[str],
        refresh_token: str,
        access_token: str | None,
        access_token_expires_at: datetime | None,
        connected_by_user_id: UUID,
        connected_at: datetime,
    ) -> WorkspaceOAuthCredentials:
        row = WorkspaceOAuthCredentials(
            workspace_id=workspace_id,
            provider=provider,
            scopes=list(scopes),
            refresh_token=refresh_token,
            access_token=access_token,
            access_token_expires_at=access_token_expires_at,
            connected_by_user_id=connected_by_user_id,
            connected_at=connected_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, integration_id: UUID) -> WorkspaceOAuthCredentials | None:
        return await self.session.get(WorkspaceOAuthCredentials, integration_id)

    async def get_for_workspace(
        self, workspace_id: UUID, provider: OAuthProvider
    ) -> list[WorkspaceOAuthCredentials]:
        result = await self.session.execute(
            select(WorkspaceOAuthCredentials)
            .where(
                WorkspaceOAuthCredentials.workspace_id == workspace_id,
                WorkspaceOAuthCredentials.provider == provider,
            )
            .order_by(WorkspaceOAuthCredentials.connected_at.desc())
        )
        return list(result.scalars().all())

    async def get_active(
        self, workspace_id: UUID, provider: OAuthProvider
    ) -> WorkspaceOAuthCredentials | None:
        result = await self.session.execute(
            select(WorkspaceOAuthCredentials)
            .where(
                WorkspaceOAuthCredentials.workspace_id == workspace_id,
                WorkspaceOAuthCredentials.provider == provider,
                WorkspaceOAuthCredentials.revoked.is_(False),
            )
            .order_by(WorkspaceOAuthCredentials.connected_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_all_for_workspace(
        self, workspace_id: UUID
    ) -> list[WorkspaceOAuthCredentials]:
        result = await self.session.execute(
            select(WorkspaceOAuthCredentials)
            .where(WorkspaceOAuthCredentials.workspace_id == workspace_id)
            .order_by(WorkspaceOAuthCredentials.connected_at.desc())
        )
        return list(result.scalars().all())

    async def update_tokens(
        self,
        creds: WorkspaceOAuthCredentials,
        *,
        access_token: str | None,
        access_token_expires_at: datetime | None,
        refresh_token: str | None = None,
    ) -> WorkspaceOAuthCredentials:
        creds.access_token = access_token
        creds.access_token_expires_at = access_token_expires_at
        if refresh_token is not None:
            creds.refresh_token = refresh_token
        await self.session.flush()
        return creds

    async def mark_revoked(
        self, creds: WorkspaceOAuthCredentials, *, revoked_at: datetime
    ) -> WorkspaceOAuthCredentials:
        creds.revoked = True
        creds.revoked_at = revoked_at
        await self.session.flush()
        return creds

    def to_public(self, creds: WorkspaceOAuthCredentials) -> dict[str, Any]:
        """Dict suitable for API response - never includes tokens."""
        return {
            "id": str(creds.id),
            "workspace_id": str(creds.workspace_id),
            "provider": creds.provider,
            "scopes": list(creds.scopes or []),
            "connected_by_user_id": str(creds.connected_by_user_id),
            "connected_at": creds.connected_at.isoformat(),
            "revoked": bool(creds.revoked),
            "revoked_at": creds.revoked_at.isoformat() if creds.revoked_at else None,
            "access_token_expires_at": (
                creds.access_token_expires_at.isoformat()
                if creds.access_token_expires_at
                else None
            ),
            "needs_reconnect": bool(creds.revoked),
        }
