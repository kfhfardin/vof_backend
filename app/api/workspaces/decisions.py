"""Decisions REST API.

  GET    /workspaces/{wid}/decisions?status=...
  GET    /workspaces/{wid}/decisions/{id}
  POST   /workspaces/{wid}/decisions/{id}/respond
  POST   /workspaces/{wid}/decisions/{id}/resolve_now  (Phase 1 §F8 CTA)

The orchestrator opens decisions via the request_manager_decision tool;
the Manager responds either via the WS-driven FE (this endpoint) or by
texting back the Workspace's number (handled in the SMS dispatcher).
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActionItem, DecisionRequest, DecisionStatus
from app.db.repositories.decisions_repo import DecisionsRepo
from app.deps import CurrentUser, get_session, get_telephony_provider, require_workspace_access
from app.errors import Conflict, NotFound, Validation
from app.logging import get_logger
from app.schemas.dashboard import ResolveNowRequest
from app.schemas.decision import (
    DecisionListResponse,
    DecisionRespondRequest,
    DecisionSummary,
)
from app.services.decisions import DecisionService
from app.telephony.base import TelephonyProvider

log = get_logger(__name__)

router = APIRouter(prefix="/workspaces/{workspace_id}/decisions", tags=["decisions"])


def _to_summary(d: DecisionRequest) -> DecisionSummary:
    return DecisionSummary(
        id=d.id,
        call_id=d.call_id,
        workspace_id=d.workspace_id,
        prompt=d.prompt,
        options=d.options,
        decision_class=d.decision_class,
        status=d.status,
        timeout_at=d.timeout_at,
        response=d.response,
        responded_at=d.responded_at,
        responded_via=d.responded_via,
        context=d.context,
        created_at=d.created_at,
    )


@router.get(
    "",
    response_model=DecisionListResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def list_decisions(
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: Annotated[DecisionStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DecisionListResponse:
    repo = DecisionsRepo(session)
    rows = await repo.list_for_workspace(workspace_id, status=status, limit=limit, offset=offset)
    return DecisionListResponse(
        decisions=[_to_summary(d) for d in rows],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{decision_id}",
    response_model=DecisionSummary,
    dependencies=[Depends(require_workspace_access)],
)
async def get_decision(
    workspace_id: UUID,
    decision_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DecisionSummary:
    repo = DecisionsRepo(session)
    d = await repo.get(decision_id)
    if d is None or d.workspace_id != workspace_id:
        raise NotFound("decision not found")
    return _to_summary(d)


@router.post(
    "/{decision_id}/respond",
    response_model=DecisionSummary,
    dependencies=[Depends(require_workspace_access)],
)
async def respond_to_decision(
    workspace_id: UUID,
    decision_id: UUID,
    body: DecisionRespondRequest,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    telephony: Annotated[TelephonyProvider, Depends(get_telephony_provider)],
) -> DecisionSummary:
    repo = DecisionsRepo(session)
    existing = await repo.get(decision_id)
    if existing is None or existing.workspace_id != workspace_id:
        raise NotFound("decision not found")

    svc = DecisionService(session, telephony=telephony)
    updated = await svc.respond(
        decision_id=decision_id,
        responder_user_id=user.id,
        response=body.response,
        via=body.via,
    )
    return _to_summary(updated)


@router.post(
    "/{decision_id}/resolve_now",
    dependencies=[Depends(require_workspace_access)],
)
async def resolve_now(
    workspace_id: UUID,
    decision_id: UUID,
    body: ResolveNowRequest,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Phase 1 §F8 "Resolve now" CTA on a timed-out decision.

    Transitions status `timed_out -> answered_late` (or `open -> answered`
    if it hasn't actually timed out yet) and records the chosen option. If
    a gated ActionItem references this decision via `payload.decision_id`,
    auto-approve it so F3's dispatcher picks it up.
    """
    repo = DecisionsRepo(session)
    decision = await repo.lock_for_update(decision_id)
    if decision is None or decision.workspace_id != workspace_id:
        raise NotFound("decision not found")
    if decision.status not in ("timed_out", "open"):
        raise Conflict(
            "decision_not_resolvable",
            details={"status": decision.status},
        )
    if body.option not in (decision.options or []):
        raise Validation(
            "option not among offered options",
            details={"option": body.option, "options": decision.options},
        )

    now = datetime.now(UTC)
    decision.status = "answered_late" if decision.status == "timed_out" else "answered"
    decision.response = body.option
    decision.responded_by_user_id = user.id
    decision.responded_via = "websocket"
    decision.responded_at = now
    await session.flush()

    # Auto-approve gated action items keyed off this decision id (F3 hook).
    auto_approved = 0
    try:
        items = list(
            (
                await session.execute(
                    select(ActionItem).where(
                        ActionItem.workspace_id == workspace_id,
                        ActionItem.status == "pending_approval",
                    )
                )
            )
            .scalars()
            .all()
        )
        for item in items:
            payload = item.payload or {}
            if str(payload.get("decision_id") or "") == str(decision_id):
                item.status = "approved"
                auto_approved += 1
        if auto_approved:
            await session.flush()
    except Exception:
        log.exception("resolve_now_auto_approve_failed", decision_id=str(decision_id))

    await session.commit()

    return {
        "decision_id": str(decision.id),
        "status": decision.status,
        "response": decision.response,
        "responded_at": decision.responded_at.isoformat() if decision.responded_at else None,
        "auto_approved_action_items": auto_approved,
    }
