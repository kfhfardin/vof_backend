"""Brain pages REST API.

Phase 0 §C8 surface:

  GET    /workspaces/{wid}/brain/pages/{slug}            current page
  GET    /workspaces/{wid}/brain/pages/{slug}/versions   version history
  POST   /workspaces/{wid}/brain/corrections             apply a correction

Slug is path-like ("accounts/acme-corp") so the route uses :path conversion.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.base import BrainPageSnapshot, BrainPageVersionSnapshot, BrainProvider
from app.deps import (
    CurrentUser,
    get_brain_provider,
    get_session,
    require_workspace_access,
)
from app.errors import NotFound
from app.schemas.brain import (
    BrainPageVersionsResponse,
    BrainPageVersionView,
    BrainPageView,
    CorrectionRequest,
)
from app.services.corrections import CorrectionService

router = APIRouter(prefix="/workspaces/{workspace_id}/brain", tags=["brain"])


def _page_to_view(p: BrainPageSnapshot) -> BrainPageView:
    return BrainPageView(
        slug=p.slug,
        kind=p.kind,
        title=p.title,
        compiled_truth=p.compiled_truth,
        timeline=p.timeline,
        tags=p.tags,
        provenance_id=p.provenance_id,
        manager_authoritative=p.manager_authoritative,
        deleted_at=p.deleted_at,
        version=p.version,
        updated_at=p.updated_at,
    )


def _version_to_view(v: BrainPageVersionSnapshot) -> BrainPageVersionView:
    return BrainPageVersionView(
        id=v.id,
        slug=v.slug,
        version=v.version,
        compiled_truth=v.compiled_truth,
        provenance_id=v.provenance_id,
        superseded_by=v.superseded_by,
        created_at=v.created_at,
    )


@router.get(
    "/pages/{slug:path}/versions",
    response_model=BrainPageVersionsResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def get_page_versions(
    workspace_id: UUID,
    slug: Annotated[str, Path(...)],
    brain: Annotated[BrainProvider, Depends(get_brain_provider)],
) -> BrainPageVersionsResponse:
    versions = await brain.list_versions(workspace_id, slug)
    return BrainPageVersionsResponse(
        slug=slug,
        versions=[_version_to_view(v) for v in versions],
    )


@router.get(
    "/pages/{slug:path}",
    response_model=BrainPageView,
    dependencies=[Depends(require_workspace_access)],
)
async def get_page(
    workspace_id: UUID,
    slug: Annotated[str, Path(...)],
    brain: Annotated[BrainProvider, Depends(get_brain_provider)],
) -> BrainPageView:
    page = await brain.get_page(workspace_id, slug)
    if page is None:
        raise NotFound(f"brain page {slug!r} not found")
    return _page_to_view(page)


@router.post(
    "/corrections",
    response_model=BrainPageView | None,
    dependencies=[Depends(require_workspace_access)],
)
async def submit_correction(
    workspace_id: UUID,
    body: CorrectionRequest,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    brain: Annotated[BrainProvider, Depends(get_brain_provider)],
) -> BrainPageView | None:
    svc = CorrectionService(session, brain=brain)
    snapshot = await svc.apply(
        workspace_id=workspace_id,
        target_slug=body.target_slug,
        kind=body.kind,
        payload=body.payload,
        rationale=body.rationale,
        corrected_by_user_id=user.id,
    )
    return _page_to_view(snapshot) if snapshot else None
