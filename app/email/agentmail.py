"""AgentMail provider implementation (Phase 1 §F6).

Talks to AgentMail's HTTP API for:
  - inbox provisioning (per Workspace),
  - outbound send,
  - re-fetching full message bodies when webhook payloads are truncated,
  - parsing webhook payloads into a normalized AgentMailEvent.

API key resolution: prefers `Settings.agentmail_api_key` once the
foundation agent ships it; falls back to the AGENTMAIL_API_KEY env var
so this provider is usable today. The provider is intentionally tolerant
of dev environments without an AgentMail account: `provision_workspace_inbox`
returns a stub inbox + logs a warning on any failure so signup keeps moving;
`send` raises on failure so the caller (email_delivery agent) can surface
an explicit skip/error.

No signature verification on incoming webhooks (speed variant).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import httpx

from app.email.base import EmailProvider
from app.email.schemas import (
    AgentMailEvent,
    ReceivedMessage,
    SentMessage,
    WorkspaceInbox,
)
from app.logging import get_logger
from app.settings import get_settings

log = get_logger(__name__)

_BASE_URL = "https://api.agentmail.to/v0"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def _resolve_api_key() -> str:
    """Pull the AgentMail API key from Settings if present, else env."""
    try:
        settings = get_settings()
        getter = getattr(settings, "agentmail_api_key", None)
        if getter is not None:
            # Support both SecretStr and bare str shapes.
            val = getter.get_secret_value() if hasattr(getter, "get_secret_value") else str(getter)
            if val:
                return val
    except Exception:  # pragma: no cover — defensive
        pass
    return os.environ.get("AGENTMAIL_API_KEY", "")


class AgentMailEmailProvider(EmailProvider):
    name: Literal["agentmail", "oauth_personal"] = "agentmail"

    def __init__(self, *, api_key: str | None = None, base_url: str = _BASE_URL) -> None:
        self._api_key = api_key if api_key is not None else _resolve_api_key()
        self._base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        h = {"content-type": "application/json", "accept": "application/json"}
        if self._api_key:
            h["authorization"] = f"Bearer {self._api_key}"
        return h

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, headers=self._headers(), timeout=_TIMEOUT)

    # ---------------- Provisioning ----------------

    async def provision_workspace_inbox(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        domain: str | None,
    ) -> WorkspaceInbox:
        """POST /inboxes. On any failure return a stub so dev keeps moving."""
        # Speed-variant: if no API key is configured (dev / CI), skip the
        # network call entirely and return the stub. Avoids the 401 round-trip
        # and any side effects on the test event loop.
        if not self._api_key:
            fallback_domain = domain or "agentmail.to"
            return WorkspaceInbox(
                inbox_id=f"stub_{slug}", address=f"{slug}@{fallback_domain}"
            )
        payload: dict[str, Any] = {"username": slug}
        if domain:
            payload["domain"] = domain
        try:
            async with await self._client() as c:
                resp = await c.post("/inboxes", json=payload)
                resp.raise_for_status()
                body = resp.json()
                inbox_id = str(body.get("inbox_id") or body.get("id") or "")
                address = str(body.get("address") or body.get("email") or "")
                if not inbox_id or not address:
                    raise RuntimeError(f"agentmail returned partial inbox payload: {body!r}")
                log.info(
                    "agentmail_inbox_provisioned",
                    workspace_id=str(workspace_id),
                    inbox_id=inbox_id,
                    address=address,
                )
                return WorkspaceInbox(inbox_id=inbox_id, address=address)
        except Exception as e:
            log.warning(
                "agentmail_provision_failed_using_stub",
                workspace_id=str(workspace_id),
                slug=slug,
                error=str(e),
            )
            fallback_domain = domain or "agentmail.to"
            return WorkspaceInbox(
                inbox_id=f"stub_{slug}",
                address=f"{slug}@{fallback_domain}",
            )

    # ---------------- Send ----------------

    async def send(
        self,
        *,
        inbox_id: str | None,
        oauth_user_id: UUID | None,
        to: str,
        subject: str,
        text: str,
        html: str | None,
        reply_to: str | None,
        headers: dict[str, str],
    ) -> SentMessage:
        if not inbox_id:
            raise RuntimeError("agentmail send requires an inbox_id")
        payload: dict[str, Any] = {
            "to": [to] if isinstance(to, str) else list(to),
            "subject": subject,
            "text": text,
        }
        if html:
            payload["html"] = html
        if reply_to:
            payload["reply_to"] = reply_to
        if headers:
            payload["headers"] = dict(headers)
        async with await self._client() as c:
            resp = await c.post(f"/inboxes/{inbox_id}/messages/send", json=payload)
            resp.raise_for_status()
            body = resp.json()
        message_id = str(body.get("message_id") or body.get("id") or "")
        thread_id = str(body.get("thread_id") or body.get("threadId") or message_id)
        ts_raw = body.get("timestamp") or body.get("sent_at") or body.get("created_at")
        timestamp = _parse_ts(ts_raw) if ts_raw else datetime.now(UTC)
        if not message_id:
            raise RuntimeError(f"agentmail send returned no message_id: {body!r}")
        return SentMessage(message_id=message_id, thread_id=thread_id, timestamp=timestamp)

    # ---------------- Full-message fetch ----------------

    async def get_full_message(
        self,
        *,
        inbox_id: str | None,
        oauth_user_id: UUID | None,
        message_id: str,
    ) -> ReceivedMessage:
        async with await self._client() as c:
            path = (
                f"/inboxes/{inbox_id}/messages/{message_id}"
                if inbox_id
                else f"/messages/{message_id}"
            )
            resp = await c.get(path)
            resp.raise_for_status()
            body = resp.json()
        return _to_received_message(body, default_inbox_id=inbox_id)

    # ---------------- Webhook parsing ----------------

    def parse_webhook(self, *, raw_body: bytes) -> AgentMailEvent | None:
        """Map AgentMail's webhook envelope to AgentMailEvent. Returns None on
        anything we can't interpret (so the route can 200-and-drop)."""
        try:
            envelope = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception:
            log.warning("agentmail_webhook_undecodable", bytes=len(raw_body))
            return None
        if not isinstance(envelope, dict):
            return None
        event_type = str(envelope.get("event") or envelope.get("type") or "")
        # Common AgentMail shapes: "message.received" / "received" etc.
        if "." not in event_type:
            event_type = f"message.{event_type}" if event_type else ""
        if event_type not in {
            "message.received",
            "message.bounced",
            "message.complained",
            "message.rejected",
            "message.delivered",
        }:
            return None
        ts_raw = envelope.get("timestamp") or envelope.get("created_at")
        try:
            timestamp = _parse_ts(ts_raw) if ts_raw else datetime.now(UTC)
        except Exception:
            timestamp = datetime.now(UTC)
        raw_msg = envelope.get("message") or envelope.get("data") or {}
        if not isinstance(raw_msg, dict):
            return None
        try:
            msg = _to_received_message(raw_msg, default_inbox_id=envelope.get("inbox_id"))
        except Exception:
            log.warning("agentmail_webhook_message_parse_failed")
            return None
        return AgentMailEvent(event_type=event_type, timestamp=timestamp, message=msg)  # type: ignore[arg-type]


# ---------------- Helpers ----------------


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        # Accept both ISO 8601 with and without trailing Z.
        v = value.replace("Z", "+00:00") if value.endswith("Z") else value
        return datetime.fromisoformat(v)
    return datetime.now(UTC)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    return [str(value)]


def _to_received_message(body: dict[str, Any], *, default_inbox_id: Any) -> ReceivedMessage:
    return ReceivedMessage(
        message_id=str(body.get("message_id") or body.get("id") or ""),
        thread_id=str(body.get("thread_id") or body.get("threadId") or ""),
        inbox_id=str(body.get("inbox_id") or default_inbox_id or "") or None,
        from_=_as_list(body.get("from") or body.get("from_")),
        to=_as_list(body.get("to")),
        subject=body.get("subject"),
        text=body.get("text"),
        html=body.get("html"),
        in_reply_to=_as_list(body.get("in_reply_to") or body.get("inReplyTo")),
        references=_as_list(body.get("references")),
        timestamp=_parse_ts(body.get("timestamp") or body.get("created_at") or body.get("date")),
    )
