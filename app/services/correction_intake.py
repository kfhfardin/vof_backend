"""CorrectionIntake service - opens an intake row that the Manager reviews
before the CorrectionService is applied.

Phase 1 callers:
  - F5 web_verifier (origin=system_web_verifier) on a contradicted claim
  - F6 email_reply_handler (origin=manager_email_reply) on a Manager reply
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.correction_intake import CorrectionIntake, CorrectionOrigin
from app.logging import get_logger

log = get_logger(__name__)


async def open_correction_intake(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    organization_id: UUID,
    target_user_id: UUID,
    origin: CorrectionOrigin,
    source_ref_id: UUID | None,
    payload: dict[str, Any],
) -> UUID:
    row = CorrectionIntake(
        workspace_id=workspace_id,
        organization_id=organization_id,
        target_user_id=target_user_id,
        origin=origin,
        source_ref_id=source_ref_id,
        payload=payload,
    )
    session.add(row)
    await session.flush()
    log.info(
        "correction_intake_opened",
        intake_id=str(row.id),
        workspace_id=str(workspace_id),
        origin=origin,
    )
    return row.id
