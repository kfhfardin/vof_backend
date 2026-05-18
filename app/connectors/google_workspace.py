"""GoogleWorkspaceConnector - OAuth + Gmail send + Calendar events.insert.

Hand-rolled httpx async calls; we explicitly do NOT pull in
google-api-python-client (sync, complicates async + drags in a large
dep tree). The surface area we need is small enough that the savings
outweigh the convenience.

Per LLD speed-variant: broad scopes requested at consent (gmail.send,
gmail.readonly, calendar.events) so a single OAuth covers both action
handlers without re-consent prompts.

State carried through the OAuth round-trip encodes `workspace_id|user_id`.
The callback handler asserts the state matches the path workspace_id +
the current authenticated user before persisting the credential row.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx

from app.connectors.base import OAuthRevokedError, refresh_if_needed
from app.db.app_session import app_session
from app.db.models import WorkspaceOAuthCredentials
from app.db.repositories.oauth_credentials_repo import OAuthCredentialsRepo
from app.logging import get_logger

log = get_logger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
CALENDAR_EVENTS_URL = (
    "https://www.googleapis.com/calendar/v3/calendars/primary/events"
)

# Broad scopes per LLD speed-variant - one consent covers both handlers.
GOOGLE_SCOPES: list[str] = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


class GoogleWorkspaceNotConfigured(RuntimeError):
    """Raised when callers try to use Google Workspace without OAuth client
    credentials configured. The connector is **optional** in Phase 1 — code
    paths that hit this should catch + degrade (skip, log, or return 503)
    rather than propagating to the user as a 500."""


def _maybe_credentials() -> tuple[str, str] | None:
    """Return (client_id, secret) if configured, else None.

    Use this when you want to *check* whether Google is wired without
    raising. Use `_client_credentials()` (raises) at the point you're
    actually about to make a Google API call you can't proceed without.
    """
    try:
        from app.settings import get_settings

        settings = get_settings()
        cid_secret = getattr(settings, "google_oauth_client_id", None)
        csecret_secret = getattr(settings, "google_oauth_client_secret", None)
        cid = cid_secret.get_secret_value() if cid_secret else ""
        csecret = csecret_secret.get_secret_value() if csecret_secret else ""
        if cid and csecret:
            return cid, csecret
    except Exception:  # noqa: BLE001 - degrade to env fallback
        log.warning("google_oauth_settings_unavailable_falling_back_to_env")

    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
    csecret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
    if cid and csecret:
        return cid, csecret
    return None


def is_google_workspace_configured() -> bool:
    """Cheap, side-effect-free check used by endpoints + mini-agents."""
    return _maybe_credentials() is not None


def _client_credentials() -> tuple[str, str]:
    """Raise `GoogleWorkspaceNotConfigured` if Google isn't wired.

    Call this from code paths that genuinely cannot proceed without
    Google. The raise is a typed signal — handlers above should catch
    `GoogleWorkspaceNotConfigured` and return 503 / skip / log.
    """
    creds = _maybe_credentials()
    if creds is None:
        raise GoogleWorkspaceNotConfigured(
            "GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are not set; "
            "Google Workspace is optional in Phase 1 and disabled in this deployment"
        )
    return creds


def _encode_state(workspace_id: UUID, user_id: UUID) -> str:
    raw = f"{workspace_id}|{user_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_state(state: str) -> tuple[UUID, UUID]:
    pad = "=" * (-len(state) % 4)
    raw = base64.urlsafe_b64decode(state + pad).decode()
    wid_str, _, uid_str = raw.partition("|")
    return UUID(wid_str), UUID(uid_str)


def _parse_draft(draft: str | dict[str, Any]) -> dict[str, Any]:
    """Coerce a rendered draft (str OR dict) into a structured shape.

    For string drafts (F3 Jinja output): first non-empty line of the form
    `Title:` or `Subject:` becomes the title; the rest is the description /
    body.
    """
    if isinstance(draft, dict):
        return draft

    lines = [ln for ln in str(draft).splitlines()]
    title = ""
    body_lines: list[str] = []
    title_taken = False
    for line in lines:
        stripped = line.strip()
        if not title_taken and stripped.lower().startswith(("title:", "subject:")):
            _, _, rest = stripped.partition(":")
            title = rest.strip()
            title_taken = True
            continue
        body_lines.append(line)
    if not title and lines:
        title = lines[0].strip() or "Untitled"
    description = "\n".join(body_lines).strip()
    return {"title": title, "description": description, "attendees": []}


def _build_rfc5322(
    *,
    sender_addr: str,
    to: str,
    subject: str,
    body_text: str,
    html: str | None = None,
    reply_to: str | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    """Build an RFC 5322 message; return base64url-encoded raw string for Gmail."""
    if html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
    else:
        msg = MIMEText(body_text, "plain", "utf-8")
    msg["From"] = formataddr((None, sender_addr)) if sender_addr else ""
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()
    if reply_to:
        msg["Reply-To"] = reply_to
    for k, v in (headers or {}).items():
        msg[k] = v
    raw_bytes = msg.as_bytes()
    return base64.urlsafe_b64encode(raw_bytes).decode().rstrip("=")


class GoogleWorkspaceConnector:
    """Async, hand-rolled OAuth + Gmail + Calendar surface.

    All methods that act on behalf of a workspace funnel through
    `_creds_with_fresh_token` so revoked tokens raise `OAuthRevokedError`
    in exactly one place.
    """

    name = "google_workspace"
    scopes = GOOGLE_SCOPES

    # ---------------- OAuth dance ----------------

    async def build_auth_url(
        self, workspace_id: UUID, user_id: UUID, redirect_uri: str
    ) -> str:
        client_id, _ = _client_credentials()
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "access_type": "offline",
            "prompt": "consent",  # ensure refresh_token is issued every time
            "include_granted_scopes": "true",
            "state": _encode_state(workspace_id, user_id),
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def handle_callback(
        self,
        workspace_id: UUID,
        user_id: UUID,
        code: str,
        redirect_uri: str,
    ) -> WorkspaceOAuthCredentials:
        client_id, client_secret = _client_credentials()
        data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(GOOGLE_TOKEN_URL, data=data)
        if resp.status_code != 200:
            log.warning(
                "google_oauth_callback_failed",
                status=resp.status_code,
                body=resp.text[:200],
            )
            raise RuntimeError(
                f"Google token exchange failed ({resp.status_code}): {resp.text[:200]}"
            )
        payload = resp.json()
        refresh_token = payload.get("refresh_token")
        if not refresh_token:
            raise RuntimeError(
                "Google response missing refresh_token - user must re-consent (prompt=consent + access_type=offline)"
            )
        access_token = payload.get("access_token")
        expires_in = int(payload.get("expires_in", 3600))
        granted_scopes = (payload.get("scope") or "").split() or list(GOOGLE_SCOPES)
        now = datetime.now(UTC)

        async with app_session() as session:
            repo = OAuthCredentialsRepo(session)
            row = await repo.create(
                workspace_id=workspace_id,
                provider="google_workspace",
                scopes=granted_scopes,
                refresh_token=refresh_token,
                access_token=access_token,
                access_token_expires_at=now + timedelta(seconds=expires_in),
                connected_by_user_id=user_id,
                connected_at=now,
            )
            await session.commit()
            await session.refresh(row)
        return row

    async def refresh_access_token(
        self, creds: WorkspaceOAuthCredentials
    ) -> WorkspaceOAuthCredentials:
        client_id, client_secret = _client_credentials()
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": creds.refresh_token,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(GOOGLE_TOKEN_URL, data=data)
        if resp.status_code == 400 or resp.status_code == 401:
            # Most commonly invalid_grant -> the user revoked OR the refresh
            # token expired (unused for 6+ months). Surface as revoked.
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001
                body = {"error": resp.text[:200]}
            err = (body.get("error") or "").lower() if isinstance(body, dict) else ""
            if err == "invalid_grant" or resp.status_code in (400, 401):
                raise OAuthRevokedError(
                    "google_workspace", creds.id, detail=json.dumps(body)[:200]
                )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Google token refresh failed ({resp.status_code}): {resp.text[:200]}"
            )
        payload = resp.json()
        new_access = payload.get("access_token")
        new_expires_in = int(payload.get("expires_in", 3600))
        # Google sometimes returns a fresh refresh_token; if not, keep the existing one.
        new_refresh = payload.get("refresh_token") or creds.refresh_token
        creds.access_token = new_access
        creds.access_token_expires_at = datetime.now(UTC) + timedelta(seconds=new_expires_in)
        creds.refresh_token = new_refresh
        return creds

    # ---------------- Action surface ----------------

    async def _creds_with_fresh_token(
        self, workspace_id: UUID
    ) -> WorkspaceOAuthCredentials:
        creds = await refresh_if_needed(workspace_id, "google_workspace")
        if creds is None:
            raise RuntimeError(
                f"no active google_workspace credentials for workspace {workspace_id}"
            )
        return creds

    async def gmail_send(
        self,
        workspace_id: UUID,
        oauth_user_id: UUID,
        *,
        to: str,
        subject: str,
        body_text: str,
        html: str | None = None,
        reply_to: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send an email via Gmail API on behalf of the connected user.

        `oauth_user_id` is accepted for API symmetry with future providers
        that distinguish per-user credentials; today we use the single
        active credential row for the workspace.
        """
        del oauth_user_id  # symmetry - one credential per workspace today
        creds = await self._creds_with_fresh_token(workspace_id)
        raw = _build_rfc5322(
            sender_addr="",  # Gmail rewrites From to the connected mailbox
            to=to,
            subject=subject,
            body_text=body_text,
            html=html,
            reply_to=reply_to,
            headers=headers,
        )
        body = {"raw": raw}
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                GMAIL_SEND_URL,
                headers={
                    "Authorization": f"Bearer {creds.access_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        if resp.status_code in (401, 403):
            try:
                err = resp.json()
            except Exception:  # noqa: BLE001
                err = {"raw": resp.text[:200]}
            reason = json.dumps(err)[:200].lower()
            if "invalid_grant" in reason or "invalid_credentials" in reason:
                raise OAuthRevokedError(
                    "google_workspace", creds.id, detail=json.dumps(err)[:200]
                )
            raise RuntimeError(
                f"gmail send unauthorized ({resp.status_code}): {resp.text[:200]}"
            )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"gmail send failed ({resp.status_code}): {resp.text[:200]}"
            )
        return resp.json()

    async def calendar_create_event(
        self,
        workspace_id: UUID,
        oauth_user_id: UUID,
        draft: str | dict[str, Any],
    ) -> dict[str, Any]:
        """Create a calendar event on the connected user's primary calendar.

        `draft` may be a dict (preferred - keys: title, description,
        start, end, attendees) or a Jinja-rendered string (F3 templates -
        first line `Title:` -> summary, rest -> description, no attendees).
        """
        del oauth_user_id  # symmetry - one credential per workspace today
        creds = await self._creds_with_fresh_token(workspace_id)
        parsed = _parse_draft(draft)

        # Default to a 30-minute slot starting "now + 1 day" if no times provided.
        # The F3 scheduler agent will pass start/end explicitly in the dict form.
        start = parsed.get("start")
        end = parsed.get("end")
        if not start or not end:
            now = datetime.now(UTC)
            start_dt = now + timedelta(days=1)
            end_dt = start_dt + timedelta(minutes=int(parsed.get("duration_min") or 30))
            start = start_dt.isoformat()
            end = end_dt.isoformat()

        event_body: dict[str, Any] = {
            "summary": parsed.get("title") or "Untitled",
            "description": parsed.get("description") or "",
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        attendees = parsed.get("attendees") or []
        if attendees:
            event_body["attendees"] = [
                {"email": a} if isinstance(a, str) else a for a in attendees
            ]

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                CALENDAR_EVENTS_URL,
                headers={
                    "Authorization": f"Bearer {creds.access_token}",
                    "Content-Type": "application/json",
                },
                json=event_body,
            )
        if resp.status_code in (401, 403):
            try:
                err = resp.json()
            except Exception:  # noqa: BLE001
                err = {"raw": resp.text[:200]}
            reason = json.dumps(err)[:200].lower()
            if "invalid_grant" in reason or "invalid_credentials" in reason:
                raise OAuthRevokedError(
                    "google_workspace", creds.id, detail=json.dumps(err)[:200]
                )
            raise RuntimeError(
                f"calendar insert unauthorized ({resp.status_code}): {resp.text[:200]}"
            )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"calendar insert failed ({resp.status_code}): {resp.text[:200]}"
            )
        return resp.json()


__all__ = [
    "GOOGLE_SCOPES",
    "GoogleWorkspaceConnector",
    "OAuthRevokedError",
    "decode_state",
]
