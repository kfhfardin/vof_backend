"""Web-verifier results REST API (F5).

  GET /workspaces/{wid}/calls/{call_id}/verifications
  GET /workspaces/{wid}/brain/pages/{slug}/verifications

The first lists every ClaimVerification row produced for a single call;
the second lists every row whose claim_subject equals the given brain
page slug (the verifier records claim_subject using the brain page slug
convention so this join is a string-equality lookup).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ClaimVerification
from app.db.repositories.claim_verifications_repo import ClaimVerificationsRepo
from app.deps import get_session, require_workspace_access
from app.errors import NotFound
from app.schemas.verification import (
    ClaimVerificationListResponse,
    ClaimVerificationView,
)

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["verifications"])


def _to_view(r: ClaimVerification) -> ClaimVerificationView:
    return ClaimVerificationView(
        id=r.id,
        workspace_id=r.workspace_id,
        organization_id=r.organization_id,
        call_id=r.call_id,
        claim_subject=r.claim_subject,
        claim_predicate=r.claim_predicate,
        claim_object=r.claim_object,
        claim_source_utterance=r.claim_source_utterance,
        status=r.status,
        confidence=r.confidence,
        evidence_url=r.evidence_url,
        evidence_snippet=r.evidence_snippet,
        contradiction_detail=r.contradiction_detail,
        correction_intake_id=r.correction_intake_id,
        created_at=r.created_at,
    )


@router.get(
    "/calls/{call_id}/verifications",
    response_model=ClaimVerificationListResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def list_verifications_for_call(
    workspace_id: UUID,
    call_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClaimVerificationListResponse:
    repo = ClaimVerificationsRepo(session)
    rows = await repo.list_for_call(call_id)
    # Defensive workspace scoping: a CASCADE FK keeps these aligned but
    # belt-and-suspenders so a stray row can't leak across tenants.
    scoped = [r for r in rows if r.workspace_id == workspace_id]
    return ClaimVerificationListResponse(verifications=[_to_view(r) for r in scoped])


@router.get(
    "/brain/pages/{slug:path}/verifications",
    response_model=ClaimVerificationListResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def list_verifications_for_brain_page(
    workspace_id: UUID,
    slug: Annotated[str, Path(...)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClaimVerificationListResponse:
    if not slug:
        raise NotFound("slug required")
    repo = ClaimVerificationsRepo(session)
    rows = await repo.list_for_claim_subject(workspace_id, slug)
    return ClaimVerificationListResponse(verifications=[_to_view(r) for r in rows])
