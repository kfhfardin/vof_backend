"""Intake API - submission + history + supersede + delete.

Per LLD §C2 - the same endpoints serve both Manager onboarding and
continuous-use updates. The `purpose` field on each item tags lifecycle
phase but behavior is identical.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IntakeBufferItem
from app.db.repositories.intake_repo import IntakeRepo
from app.deps import (
    CurrentUser,
    get_intake_processor,
    get_object_store,
    get_session,
    require_workspace_access,
)
from app.schemas.intake import (
    IntakeItemSummary,
    IntakeListResponse,
    IntakeReviewResponse,
    IntakeReviewSummary,
    IntakeSupersedeRequest,
    IntakeTextSubmission,
    IntakeUploadResponse,
)
from app.services.intake_processing import process_intake_item
from app.services.intake_processor import IntakeProcessor
from app.storage.base import ObjectStore

router = APIRouter(
    prefix="/workspaces/{workspace_id}/intake",
    tags=["intake"],
)


def _to_summary(item: IntakeBufferItem) -> IntakeItemSummary:
    return IntakeItemSummary(
        id=item.id,
        workspace_id=item.workspace_id,
        source=item.source,
        purpose=item.purpose,
        status=item.status,
        extractor_used=item.extractor_used,
        content_filename=item.content_filename,
        content_mime=item.content_mime,
        content_sha256=item.content_sha256,
        classification=item.classification,
        handler_result=item.handler_result,
        superseded_by_item_id=item.superseded_by_item_id,
        error=item.error,
        created_at=item.created_at,
    )


@router.post(
    "/text",
    status_code=status.HTTP_201_CREATED,
    response_model=IntakeUploadResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def submit_text(
    workspace_id: UUID,
    body: IntakeTextSubmission,
    user: CurrentUser,
    svc: Annotated[IntakeProcessor, Depends(get_intake_processor)],
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[ObjectStore, Depends(get_object_store)],
) -> IntakeUploadResponse:
    result = await svc.submit_text(
        workspace_id=workspace_id,
        organization_id=user.organization_id,
        submitted_by_user_id=user.id,
        purpose=body.purpose,
        text=body.text,
    )
    if not result.deduped:
        # Eager processing in Phase 0 - arq enqueue lands later.
        await process_intake_item(result.item.id, session=session, storage=storage)
        await session.refresh(result.item)
    return IntakeUploadResponse(item=_to_summary(result.item), deduped=result.deduped)


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    response_model=IntakeUploadResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def submit_upload(
    workspace_id: UUID,
    user: CurrentUser,
    svc: Annotated[IntakeProcessor, Depends(get_intake_processor)],
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[ObjectStore, Depends(get_object_store)],
    file: Annotated[UploadFile, File(...)],
    purpose: Annotated[
        Literal["onboarding", "ongoing_update", "correction"],
        Form(),
    ] = "ongoing_update",
) -> IntakeUploadResponse:
    if file.filename is None:
        from app.errors import Validation

        raise Validation("upload requires a filename")
    result = await svc.submit_upload(
        workspace_id=workspace_id,
        organization_id=user.organization_id,
        submitted_by_user_id=user.id,
        purpose=purpose,
        blob=file.file,
        filename=file.filename,
        content_mime=file.content_type,
    )
    if not result.deduped:
        await process_intake_item(result.item.id, session=session, storage=storage)
        await session.refresh(result.item)
    return IntakeUploadResponse(item=_to_summary(result.item), deduped=result.deduped)


@router.get(
    "/items",
    response_model=IntakeListResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def list_items(
    workspace_id: UUID,
    svc: Annotated[IntakeProcessor, Depends(get_intake_processor)],
    purpose: Annotated[Literal["onboarding", "ongoing_update", "correction"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IntakeListResponse:
    items = await svc.list(workspace_id, purpose=purpose, limit=limit, offset=offset)
    return IntakeListResponse(items=[_to_summary(i) for i in items], limit=limit, offset=offset)


@router.get(
    "/items/{item_id}",
    response_model=IntakeItemSummary,
    dependencies=[Depends(require_workspace_access)],
)
async def get_item(
    workspace_id: UUID,
    item_id: UUID,
    svc: Annotated[IntakeProcessor, Depends(get_intake_processor)],
) -> IntakeItemSummary:
    item = await svc.get(item_id)
    if item.workspace_id != workspace_id:
        from app.errors import NotFound

        raise NotFound("intake item not found")
    return _to_summary(item)


@router.get(
    "/items/{item_id}/download",
    dependencies=[Depends(require_workspace_access)],
)
async def download_item(
    workspace_id: UUID,
    item_id: UUID,
    svc: Annotated[IntakeProcessor, Depends(get_intake_processor)],
) -> RedirectResponse:
    item = await svc.get(item_id)
    if item.workspace_id != workspace_id:
        from app.errors import NotFound

        raise NotFound("intake item not found")
    url = await svc.download_url(item)
    return RedirectResponse(url, status_code=302)


@router.post(
    "/items/{item_id}/supersede",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_workspace_access)],
)
async def supersede_item(
    workspace_id: UUID,
    item_id: UUID,
    body: IntakeSupersedeRequest,
    svc: Annotated[IntakeProcessor, Depends(get_intake_processor)],
) -> Response:
    await svc.supersede(old_item_id=item_id, new_item_id=body.new_item_id)
    return Response(status_code=204)


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_workspace_access)],
)
async def delete_item(
    workspace_id: UUID,
    item_id: UUID,
    svc: Annotated[IntakeProcessor, Depends(get_intake_processor)],
    force: Annotated[bool, Query()] = False,
) -> Response:
    await svc.soft_delete(item_id, force=force)
    return Response(status_code=204)


@router.post(
    "/items/{item_id}/process",
    response_model=IntakeItemSummary,
    dependencies=[Depends(require_workspace_access)],
)
async def reprocess_item(
    workspace_id: UUID,
    item_id: UUID,
    svc: Annotated[IntakeProcessor, Depends(get_intake_processor)],
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[ObjectStore, Depends(get_object_store)],
) -> IntakeItemSummary:
    """Trigger or retry processing for an item.

    Idempotent: terminal items (ingested/failed/deleted/superseded) are a noop.
    """
    item = await svc.get(item_id)
    if item.workspace_id != workspace_id:
        from app.errors import NotFound

        raise NotFound("intake item not found")
    await process_intake_item(item_id, session=session, storage=storage)
    refreshed = await svc.get(item_id)
    return _to_summary(refreshed)


@router.get(
    "/review",
    response_model=IntakeReviewResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def review_view(
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IntakeReviewResponse:
    """Stage 5 verification surface.

    Aggregates what the pipeline did since the Manager last looked:
    counts per status, recent low-confidence items needing review.
    Per LLD §C2 / HLD §7.1.6.
    """
    repo = IntakeRepo(session)
    # Pull a bounded recent window; enough to power the FE's review pane.
    recent = await repo.list_for_workspace(workspace_id, limit=200, offset=0)
    counts: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    needs_review: list[IntakeItemSummary] = []
    for item in recent:
        counts[item.status] = counts.get(item.status, 0) + 1
        if item.classification and "kind" in item.classification:
            kind = str(item.classification["kind"])
            by_kind[kind] = by_kind.get(kind, 0) + 1
        if item.status == "needs_review":
            needs_review.append(_to_summary(item))

    return IntakeReviewResponse(
        summary=IntakeReviewSummary(
            total_recent=len(recent),
            by_status=counts,
            by_kind=by_kind,
            needs_review_count=counts.get("needs_review", 0),
            ingested_count=counts.get("ingested", 0),
            failed_count=counts.get("failed", 0),
        ),
        needs_review=needs_review,
    )
