"""EmailProvider Protocol (Phase 1 §F6).

Two implementations live alongside this file:
  - AgentMailEmailProvider: Workspace-hosted inbox via AgentMail's HTTP API.
  - OAuthPersonalEmailProvider: Gmail send via the Manager's connected OAuth
    credentials (F3 personal-mailbox route; depends on F9 connector).
"""

from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from app.email.schemas import (
    AgentMailEvent,
    ReceivedMessage,
    SentMessage,
    WorkspaceInbox,
)


class EmailProvider(Protocol):
    name: Literal["agentmail", "oauth_personal"]

    async def provision_workspace_inbox(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        domain: str | None,
    ) -> WorkspaceInbox: ...

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
    ) -> SentMessage: ...

    async def get_full_message(
        self,
        *,
        inbox_id: str | None,
        oauth_user_id: UUID | None,
        message_id: str,
    ) -> ReceivedMessage: ...

    def parse_webhook(self, *, raw_body: bytes) -> AgentMailEvent | None: ...
