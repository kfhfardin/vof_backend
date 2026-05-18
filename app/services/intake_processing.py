"""Drives an IntakeBufferItem through extract -> classify -> handler.

Phase 0 §C2: this is the function the arq worker will call. It is also
callable directly from the API (eager mode) so unit/integration tests can
walk the pipeline end-to-end without spinning up arq.

The function is idempotent: a second call with the same item_id is safe
as long as the item is not already in a terminal state (ingested / failed /
deleted / superseded).
"""

from __future__ import annotations

from typing import BinaryIO
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.intake_repo import IntakeRepo
from app.db.repositories.workspaces_repo import WorkspacesRepo
from app.errors import NotFound
from app.logging import get_logger
from app.services.intake_extractors import ExtractedContent, UnsupportedFormat, registry
from app.services.intake_handlers import HandlerInput, resolve_handler
from app.skills import SkillContext, SkillRegistry
from app.storage.base import ObjectStore

log = get_logger(__name__)

CONFIDENCE_THRESHOLD = 0.7
TERMINAL_STATUSES = {"ingested", "failed", "deleted", "superseded"}


def _classifier_input_dict(
    *,
    workspace_id: UUID,
    workspace_name: str,
    content: str,
    source: str,
    filename: str | None,
) -> dict[str, object]:
    return {
        "workspace_id": str(workspace_id),
        "workspace_name": workspace_name,
        "content": content[:50_000],  # hard cap to keep the prompt bounded
        "source": source,
        "filename": filename,
        "roster": [],  # roster comes from FieldEmployee in §C3+
        "known_accounts": [],  # brain hits come once §C8 lands
    }


async def _extract_content(
    session: AsyncSession,
    storage: ObjectStore,
    item_id: UUID,
) -> tuple[str, str | None]:
    """Materialize the text content to classify and the extractor used.

    For text submissions, returns the stored text directly.
    For uploads, downloads the blob, resolves the right extractor, runs it.
    """
    repo = IntakeRepo(session)
    item = await repo.get(item_id)
    if item is None:
        raise NotFound(f"intake item {item_id} not found")

    if item.content_text:
        return item.content_text, None

    if not item.content_blob_key:
        raise RuntimeError(f"item {item_id} has neither text nor blob")

    blob_bytes = await storage.get(item.content_blob_key)
    extractor = registry.resolve(item.content_mime, item.content_filename or "unknown")
    import io

    extracted: ExtractedContent = extractor.extract(
        io.BytesIO(blob_bytes), item.content_filename or "unknown"
    )

    parts: list[str] = []
    if extracted.text:
        parts.append(extracted.text)
    if extracted.rows:
        # Render a sample for the classifier (first 25 rows is plenty of signal)
        sample = extracted.rows[:25]
        parts.append(f"[rows count={len(extracted.rows)} sample_first=25]")
        for r in sample:
            parts.append(" | ".join(f"{k}={v}" for k, v in r.items()))
    text = "\n".join(parts).strip()
    if not text and extracted.warnings:
        text = f"(no text extracted; warnings: {'; '.join(extracted.warnings)})"
    return text, extractor.name


async def process_intake_item(
    item_id: UUID,
    *,
    session: AsyncSession,
    storage: ObjectStore,
) -> str:
    """Run the full pipeline; returns the final status."""
    repo = IntakeRepo(session)
    item = await repo.get(item_id)
    if item is None:
        raise NotFound(f"intake item {item_id} not found")
    if item.status in TERMINAL_STATUSES:
        log.info("process_intake_item_terminal_noop", item_id=str(item_id), status=item.status)
        return item.status

    workspace = await WorkspacesRepo(session).get_by_id(item.workspace_id)
    if workspace is None:
        raise NotFound(f"workspace {item.workspace_id} not found")

    # 1. Extract content
    try:
        await repo.update_status(item.id, status="extracting")
        await session.commit()
        text, extractor_name = await _extract_content(session, storage, item.id)
        if extractor_name:
            await repo.update_status(item.id, extractor_used=extractor_name)
    except UnsupportedFormat as e:
        await repo.update_status(item.id, status="failed", error=f"unsupported_format: {e}")
        await session.commit()
        return "failed"
    except Exception as e:
        log.exception("intake_extract_failed", item_id=str(item_id))
        await repo.update_status(item.id, status="failed", error=f"extract_failed: {e}")
        await session.commit()
        return "failed"

    if not text.strip():
        await repo.update_status(item.id, status="needs_review", error="empty_content_after_extraction")
        await session.commit()
        return "needs_review"

    # 2. Classify
    try:
        skill = SkillRegistry.get("classifier")
        clf_in = skill.input_schema.model_validate(
            _classifier_input_dict(
                workspace_id=item.workspace_id,
                workspace_name=workspace.name,
                content=text,
                source=item.source,
                filename=item.content_filename,
            )
        )
        ctx = SkillContext(workspace_id=item.workspace_id)
        clf_out = await skill.run(clf_in, ctx)
        classification = clf_out.model_dump(mode="json")
        await repo.update_status(item.id, status="classified", classification=classification)
        await session.commit()
    except Exception as e:
        log.exception("intake_classify_failed", item_id=str(item_id))
        await repo.update_status(item.id, status="failed", error=f"classify_failed: {e}")
        await session.commit()
        return "failed"

    # 3. Confidence gate
    if float(classification.get("confidence", 0.0)) < CONFIDENCE_THRESHOLD:
        await repo.update_status(
            item.id,
            status="needs_review",
            error=f"low_confidence: {classification.get('confidence')}",
        )
        await session.commit()
        return "needs_review"

    # 4. Dispatch to typed handler. Pass the brain provider so handlers can
    # actually upsert pages (§C8); they use their own DB sessions internally.
    from app.deps import get_brain_provider

    brain = get_brain_provider()
    try:
        handler = resolve_handler(classification["scope"])
        result = await handler.ingest(
            HandlerInput(
                workspace_id=item.workspace_id,
                organization_id=item.organization_id,
                item_id=item.id,
                content_text=text,
                classification=classification,
            ),
            brain=brain,
        )
        # If the handler signaled a conflict, surface as needs_review instead
        # of ingested (the brain side wrote a timeline note but not the page).
        from app.db.models import IntakeStatus

        final_status: IntakeStatus = "needs_review" if result.get("needs_review") else "ingested"
        await repo.update_status(item.id, status=final_status, handler_result=result)
        await session.commit()
        return final_status
    except Exception as e:
        log.exception("intake_handler_failed", item_id=str(item_id))
        await repo.update_status(item.id, status="failed", error=f"handler_failed: {e}")
        await session.commit()
        return "failed"


async def submit_text_with_processing(
    *,
    workspace_id: UUID,
    organization_id: UUID,
    submitted_by_user_id: UUID,
    purpose: str,
    text: str,
    session: AsyncSession,
    storage: ObjectStore,
    eager: bool = True,
) -> UUID:
    """Helper for the API: create + (optionally) process synchronously.

    eager=True (Phase 0 default) processes inline so the response includes
    final status. Once arq is wired, callers pass eager=False to enqueue.
    """
    from app.services.intake_processor import IntakeProcessor

    proc = IntakeProcessor(session, storage)
    result = await proc.submit_text(
        workspace_id=workspace_id,
        organization_id=organization_id,
        submitted_by_user_id=submitted_by_user_id,
        purpose=purpose,  # type: ignore[arg-type]
        text=text,
    )
    if eager and not result.deduped:
        await process_intake_item(result.item.id, session=session, storage=storage)
    return result.item.id


async def submit_upload_with_processing(
    *,
    workspace_id: UUID,
    organization_id: UUID,
    submitted_by_user_id: UUID,
    purpose: str,
    blob: BinaryIO,
    filename: str,
    content_mime: str | None,
    session: AsyncSession,
    storage: ObjectStore,
    eager: bool = True,
) -> UUID:
    from app.services.intake_processor import IntakeProcessor

    proc = IntakeProcessor(session, storage)
    result = await proc.submit_upload(
        workspace_id=workspace_id,
        organization_id=organization_id,
        submitted_by_user_id=submitted_by_user_id,
        purpose=purpose,  # type: ignore[arg-type]
        blob=blob,
        filename=filename,
        content_mime=content_mime,
    )
    if eager and not result.deduped:
        await process_intake_item(result.item.id, session=session, storage=storage)
    return result.item.id
