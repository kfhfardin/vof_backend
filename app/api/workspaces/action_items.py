"""Action items REST API (Phase 1 F3).

    GET    /workspaces/{wid}/action_items?status=...&limit=&offset=
    POST   /workspaces/{wid}/action_items/{id}/approve
    POST   /workspaces/{wid}/action_items/{id}/reject
    PATCH  /workspaces/{wid}/action_items/{id}
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActionItem, ActionItemHandler, ActionItemStatus
from app.db.repositories.action_items_repo import ActionItemsRepo
from app.deps import get_session, require_workspace_access
from app.errors import Conflict, NotFound

router = APIRouter(prefix="/workspaces/{workspace_id}/action_items", tags=["action_items"])


class ActionItemDTO(BaseModel):
    id: UUID
    workspace_id: UUID
    call_id: UUID | None
    title: str
    description: str | None
    due_at: datetime | None
    payload: dict[str, Any]
    status: str
    extracted_by: str | None
    confidence: float | None
    handler: str
    handler_outcome: dict[str, Any] | None
    handler_executed_at: datetime | None
    handler_attempts: int
    handler_error: str | None
    created_at: datetime


class ActionItemListResponse(BaseModel):
    action_items: list[ActionItemDTO]
    limit: int
    offset: int


class ActionItemPatch(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    due_at: datetime | None = None
    payload: dict[str, Any] | None = None
    handler: ActionItemHandler | None = None


def _to_dto(row: ActionItem) -> ActionItemDTO:
    return ActionItemDTO(
        id=row.id,
        workspace_id=row.workspace_id,
        call_id=row.call_id,
        title=row.title,
        description=row.description,
        due_at=row.due_at,
        payload=row.payload or {},
        status=row.status,
        extracted_by=row.extracted_by,
        confidence=row.confidence,
        handler=row.handler,
        handler_outcome=row.handler_outcome,
        handler_executed_at=row.handler_executed_at,
        handler_attempts=row.handler_attempts,
        handler_error=row.handler_error,
        created_at=row.created_at,
    )


@router.get(
    "",
    response_model=ActionItemListResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def list_action_items(
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: Annotated[ActionItemStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ActionItemListResponse:
    repo = ActionItemsRepo(session)
    rows = await repo.list_for_workspace(workspace_id, status=status, limit=limit, offset=offset)
    return ActionItemListResponse(
        action_items=[_to_dto(r) for r in rows],
        limit=limit,
        offset=offset,
    )


async def _load_for_ws(
    session: AsyncSession, workspace_id: UUID, action_item_id: UUID
) -> ActionItem:
    repo = ActionItemsRepo(session)
    row = await repo.get(action_item_id)
    if row is None or row.workspace_id != workspace_id:
        raise NotFound("action item not found")
    return row


@router.post(
    "/{action_item_id}/approve",
    response_model=ActionItemDTO,
    dependencies=[Depends(require_workspace_access)],
)
async def approve_action_item(
    workspace_id: UUID,
    action_item_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ActionItemDTO:
    repo = ActionItemsRepo(session)
    row = await _load_for_ws(session, workspace_id, action_item_id)
    if row.status not in ("pending_approval", "needs_review"):
        raise Conflict(f"cannot approve from status={row.status}")
    await repo.update_status(row, status="approved")
    await session.commit()
    return _to_dto(row)


@router.post(
    "/{action_item_id}/reject",
    response_model=ActionItemDTO,
    dependencies=[Depends(require_workspace_access)],
)
async def reject_action_item(
    workspace_id: UUID,
    action_item_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ActionItemDTO:
    repo = ActionItemsRepo(session)
    row = await _load_for_ws(session, workspace_id, action_item_id)
    if row.status not in ("pending_approval", "needs_review"):
        raise Conflict(f"cannot reject from status={row.status}")
    await repo.update_status(row, status="rejected")
    await session.commit()
    return _to_dto(row)


@router.patch(
    "/{action_item_id}",
    response_model=ActionItemDTO,
    dependencies=[Depends(require_workspace_access)],
)
async def edit_action_item(
    workspace_id: UUID,
    action_item_id: UUID,
    body: ActionItemPatch,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ActionItemDTO:
    row = await _load_for_ws(session, workspace_id, action_item_id)
    if row.status not in ("pending_approval", "needs_review"):
        raise Conflict(f"cannot edit from status={row.status}")
    if body.title is not None:
        row.title = body.title
    if body.description is not None:
        row.description = body.description
    if body.due_at is not None:
        row.due_at = body.due_at
    if body.payload is not None:
        row.payload = body.payload
    if body.handler is not None:
        row.handler = body.handler
    await session.flush()
    await session.commit()
    return _to_dto(row)
