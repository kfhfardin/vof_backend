"""WorkspaceOAuthCredentials - OAuth tokens for third-party connectors.

Phase 1 §F9 ships the Google Workspace connector. Per the LLD speed-variant:
tokens are stored in PLAINTEXT TEXT columns. No KMS envelope. No scope
minimization (broad scopes requested at consent time so a single OAuth
covers both Gmail send + Calendar event create without re-consent).

`provider` is String(32) rather than an enum so future providers
(microsoft_365, slack) are a one-line addition.

When `revoked=True` the row is retained for audit; downstream consumers
surface `needs_reconnect` and start a fresh OAuth dance against a new row.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey

OAuthProvider = Literal["google_workspace"]


class WorkspaceOAuthCredentials(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "workspace_oauth_credentials"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("manager_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[OAuthProvider] = mapped_column(String(32), nullable=False, index=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    # Plaintext per LLD speed-variant. If this becomes a compliance concern,
    # swap for an encrypted_refresh_token: bytes column + envelope KMS.
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    connected_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
