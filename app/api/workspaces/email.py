"""Email audit endpoint (Phase 1 §F6).

  GET /workspaces/{wid}/email/messages

Returns the last 100 EmailMessage rows for the workspace, newest first.
Audit-only surface for the FE; opt-in flags are written via the existing
`PATCH /workspaces/{wid}/config`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EmailMessage
from app.db.repositories.email_messages_repo import EmailMessagesRepo
from app.deps import get_session, require_workspace_access

router = APIRouter(prefix="/workspaces/{workspace_id}/email", tags=["email"])


class EmailMessageSummary(BaseModel):
    id: UUID
    workspace_id: UUID
    provider: str
    provider_message_id: str
    provider_thread_id: str
    trigger_kind: str
    trigger_ref_id: UUID
    recipient_class: str
    recipient_addr: str
    sent_at: datetime
    created_at: datetime


class EmailMessageListResponse(BaseModel):
    messages: list[EmailMessageSummary]
    limit: int
    offset: int


def _to_summary(m: EmailMessage) -> EmailMessageSummary:
    return EmailMessageSummary(
        id=m.id,
        workspace_id=m.workspace_id,
        provider=m.provider,
        provider_message_id=m.provider_message_id,
        provider_thread_id=m.provider_thread_id,
        trigger_kind=m.trigger_kind,
        trigger_ref_id=m.trigger_ref_id,
        recipient_class=m.recipient_class,
        recipient_addr=m.recipient_addr,
        sent_at=m.sent_at,
        created_at=m.created_at,
    )


@router.get(
    "/messages",
    response_model=EmailMessageListResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def list_email_messages(
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EmailMessageListResponse:
    repo = EmailMessagesRepo(session)
    rows = await repo.list_for_workspace(workspace_id, limit=limit, offset=offset)
    return EmailMessageListResponse(
        messages=[_to_summary(m) for m in rows],
        limit=limit,
        offset=offset,
    )
