"""Persist `ActionItemCandidate` rows for a call."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActionItem, Call
from app.db.repositories.action_items_repo import ActionItemsRepo
from app.services.action_items.heuristic_extractor import ActionItemCandidate


async def save_action_items(
    session: AsyncSession,
    *,
    call: Call,
    candidates: list[ActionItemCandidate],
) -> list[ActionItem]:
    """Create ActionItem rows from candidates. Returns the persisted rows."""
    if not candidates:
        return []
    repo = ActionItemsRepo(session)
    rows: list[ActionItem] = []
    for c in candidates:
        row = await repo.create(
            workspace_id=call.workspace_id,
            organization_id=call.organization_id,
            call_id=call.id,
            title=c.title,
            description=c.description,
            due_at=None,
            payload=c.payload,
            status="pending_approval",
            extracted_by=c.extracted_by,
            confidence=c.confidence,
            handler=c.handler,
        )
        rows.append(row)
    return rows
