"""Email surface schemas (Phase 1 §F6).

Provider-agnostic Pydantic v2 models that flow through the EmailProvider
Protocol. AgentMail and Gmail map their native payloads to these shapes;
mini-agents downstream only depend on these.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SentMessage(BaseModel):
    """Result of a successful provider send."""

    message_id: str
    thread_id: str
    timestamp: datetime


class ReceivedMessage(BaseModel):
    """Inbound message as surfaced by the provider (webhook or full-fetch).

    `from_` aliases JSON `from` (Python reserved word). Use
    `model_dump(by_alias=True)` for round-trips.
    """

    model_config = ConfigDict(populate_by_name=True)

    message_id: str
    thread_id: str
    inbox_id: str | None = None
    from_: list[str] = Field(default_factory=list, alias="from")
    to: list[str] = Field(default_factory=list)
    subject: str | None = None
    text: str | None = None
    html: str | None = None
    in_reply_to: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    timestamp: datetime


class AgentMailEvent(BaseModel):
    """Normalized AgentMail webhook event."""

    event_type: Literal[
        "message.received",
        "message.bounced",
        "message.complained",
        "message.rejected",
        "message.delivered",
    ]
    timestamp: datetime
    message: ReceivedMessage


class WorkspaceInbox(BaseModel):
    """AgentMail-hosted Workspace inbox identifiers."""

    inbox_id: str
    address: str


class ComposedEmail(BaseModel):
    """A rendered outbound email ready for provider.send()."""

    subject: str
    text: str
    html: str | None = None
