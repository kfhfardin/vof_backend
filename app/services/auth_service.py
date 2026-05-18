"""Authentication service.

Implements login + refresh + logout. Signup is delegated to
WorkspaceProvisioningService since it has to create org/workspace/brain/AP-number
in addition to the user.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RefreshToken, User
from app.db.repositories.refresh_tokens_repo import RefreshTokensRepo
from app.db.repositories.users_repo import UsersRepo
from app.errors import Conflict, Forbidden, NotFound
from app.security.hashing import verify_password
from app.security.jwt import InvalidToken, decode_token, encode_token
from app.settings import get_settings


@dataclass
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UsersRepo(session)
        self.refresh_tokens = RefreshTokensRepo(session)

    # ---- Login ----

    async def login(self, *, email: str, password: str) -> tuple[User, IssuedTokens]:
        user = await self.users.get_by_email(email.lower())
        if user is None or not verify_password(password, user.password_hash):
            raise Forbidden("invalid_credentials")
        tokens = await self._issue_pair(user)
        return user, tokens

    # ---- Refresh ----

    async def refresh(self, refresh_token_str: str) -> IssuedTokens:
        payload = decode_token(refresh_token_str, expected_type="refresh")
        jti = payload["jti"]

        record = await self.refresh_tokens.get_by_jti(jti)
        if record is None:
            # Signed by us but not in DB - shouldn't happen unless table was reset
            raise InvalidToken("refresh token not recognized")
        if record.revoked_at is not None:
            # Token was rotated and someone is replaying the old one.
            # CVE-class reuse - revoke the whole chain for safety.
            await self.refresh_tokens.revoke_user_chain(record.user_id, reason="reuse_detected")
            await self.session.commit()
            raise Forbidden("refresh_reuse_detected")
        if record.expires_at < datetime.now(UTC):
            raise InvalidToken("refresh token expired")

        user = await self.users.get_by_id(record.user_id)
        if user is None:
            raise NotFound("user no longer exists")

        # Mark the consumed token revoked and issue a new pair. Commit
        # BEFORE returning — otherwise app_session() rolls back the
        # rotation on close, the old token stays usable, and
        # reuse-detection never fires on the next replay. Phase 0
        # services own their commits; get_session does not commit on
        # dependency teardown.
        await self.refresh_tokens.revoke(jti, reason="rotated")
        new_tokens = await self._issue_pair(user, parent_jti=jti)
        await self.session.commit()
        return new_tokens

    # ---- Logout ----

    async def logout(self, refresh_token_str: str) -> None:
        try:
            payload = decode_token(refresh_token_str, expected_type="refresh")
        except InvalidToken:
            return  # idempotent
        await self.refresh_tokens.revoke(payload["jti"], reason="logout")
        # See refresh() — services own their commits; without this the
        # revoke is rolled back when app_session() closes and the token
        # stays usable post-logout.
        await self.session.commit()

    # ---- Internal ----

    async def _issue_pair(self, user: User, *, parent_jti: str | None = None) -> IssuedTokens:
        settings = get_settings()
        access_token, _, _ = encode_token(
            user_id=user.id,
            organization_id=user.organization_id,
            workspace_id=user.workspace_id,
            role=user.role,
            token_type="access",
        )
        refresh_token, refresh_jti, refresh_expires_at = encode_token(
            user_id=user.id,
            organization_id=user.organization_id,
            workspace_id=user.workspace_id,
            role=user.role,
            token_type="refresh",
        )
        await self.refresh_tokens.record(
            user_id=user.id,
            jti=refresh_jti,
            expires_at=refresh_expires_at,
            parent_jti=parent_jti,
        )
        return IssuedTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.jwt_access_ttl_seconds,
        )


async def ensure_email_available(session: AsyncSession, email: str) -> None:
    repo = UsersRepo(session)
    existing = await repo.get_by_email(email.lower())
    if existing is not None:
        raise Conflict("email_taken")


__all__ = [
    "AuthService",
    "IssuedTokens",
    "RefreshToken",
    "ensure_email_available",
]
