"""Refresh token table.

Refresh tokens are rotated on every use (each refresh issues a new pair;
the prior refresh is marked revoked). If a revoked token is presented again,
the entire chain is revoked - that's the CVE-class reuse detection.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey


class RefreshToken(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The token's jti claim - what we look up on /refresh
    jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Rotation chain: the previous refresh that issued this one (null on first issue)
    parent_jti: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # If revoked because the token was *reused* after rotation (CVE pattern), tag it.
    revoked_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
