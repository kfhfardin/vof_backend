"""OAuthPersonalEmailProvider (Phase 1 §F6, depends on F9).

Used by the email_delivery agent when `delivery_route="oauth_personal"`
(the F3 personal-mailbox route). Send is delegated to the F9
GoogleWorkspaceConnector; provisioning / inbound webhooks are not
supported by this route (AgentMail owns those).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from app.connectors.google_workspace import (
    GoogleWorkspaceConnector,
    GoogleWorkspaceNotConfigured,
)
from app.email.base import EmailProvider
from app.email.schemas import (
    AgentMailEvent,
    ReceivedMessage,
    SentMessage,
    WorkspaceInbox,
)


class OAuthPersonalEmailProvider(EmailProvider):
    name: Literal["agentmail", "oauth_personal"] = "oauth_personal"

    async def provision_workspace_inbox(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        domain: str | None,
    ) -> WorkspaceInbox:
        raise NotImplementedError(
            "oauth_personal does not provision workspace inboxes; use AgentMail"
        )

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
        # The EmailProvider Protocol does not include workspace_id; the
        # caller (email_delivery agent) stuffs it into `headers["X-Workspace-Id"]`
        # for this route so the F9 connector can resolve credentials.
        workspace_id_str = (headers or {}).get("X-Workspace-Id")
        if not workspace_id_str:
            raise RuntimeError(
                "oauth_personal send requires X-Workspace-Id header"
            )
        workspace_id = UUID(workspace_id_str)
        if oauth_user_id is None:
            raise RuntimeError("oauth_personal send requires oauth_user_id")

        # Strip the internal-only routing header before sending.
        forward_headers = {
            k: v for k, v in (headers or {}).items() if k != "X-Workspace-Id"
        }

        connector = GoogleWorkspaceConnector()
        try:
            result = await connector.gmail_send(
                workspace_id=workspace_id,
                oauth_user_id=oauth_user_id,
                to=to,
                subject=subject,
                body_text=text,
                html=html,
                reply_to=reply_to,
                headers=forward_headers,
            )
        except GoogleWorkspaceNotConfigured as e:
            # Optional integration; surface as NotImplementedError so the
            # email_delivery agent maps it to `oauth_connector_unavailable`.
            raise NotImplementedError(
                "personal-account (OAuth) email send requires Google Workspace "
                "client credentials (GOOGLE_OAUTH_CLIENT_ID / *_SECRET)"
            ) from e
        # Gmail's send response is a dict: {"id": "...", "threadId": "..."}.
        return SentMessage(
            message_id=str(result.get("id") or ""),
            thread_id=str(result.get("threadId") or result.get("id") or ""),
            timestamp=datetime.now(UTC),
        )

    async def get_full_message(
        self,
        *,
        inbox_id: str | None,
        oauth_user_id: UUID | None,
        message_id: str,
    ) -> ReceivedMessage:
        raise NotImplementedError("oauth_personal does not handle inbound webhooks")

    def parse_webhook(self, *, raw_body: bytes) -> AgentMailEvent | None:
        raise NotImplementedError("oauth_personal does not handle inbound webhooks")
