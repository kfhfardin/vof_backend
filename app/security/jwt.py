"""JWT encode/decode for access + refresh tokens.

Claims (LLD §A7):
  sub  - user_id
  org  - organization_id
  ws   - workspace_id (null for org_admin)
  role - manager | org_admin | rep | viewer
  iat / exp / jti - standard
  type - "access" | "refresh"
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt

from app.errors import VotFError
from app.settings import get_settings


class InvalidToken(VotFError):
    http_status = 401
    code = "invalid_token"


TokenType = Literal["access", "refresh"]


def encode_token(
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    role: str,
    token_type: TokenType,
    ttl_seconds: int | None = None,
    jti: str | None = None,
) -> tuple[str, str, datetime]:
    """Return (token, jti, expires_at)."""
    settings = get_settings()
    if ttl_seconds is None:
        ttl_seconds = (
            settings.jwt_access_ttl_seconds if token_type == "access" else settings.jwt_refresh_ttl_seconds
        )
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=ttl_seconds)
    jti = jti or str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": str(organization_id),
        "ws": str(workspace_id) if workspace_id else None,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
        "type": token_type,
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, jti, expires_at


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as e:
        raise InvalidToken("token expired") from e
    except jwt.InvalidTokenError as e:
        raise InvalidToken(f"invalid token: {e}") from e

    if expected_type and payload.get("type") != expected_type:
        raise InvalidToken(f"expected {expected_type} token, got {payload.get('type')}")
    return payload
