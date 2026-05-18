"""IntakeProcessor service - submission + extraction.

Phase 0 Chunk 2 scope: submission, extraction, supersession, delete.
The classifier + typed handlers land in Chunk 3 alongside the skill loader.
For now, extraction stops at 'extracting' status; the worker that drives
processing through to 'ingested' is wired when the classifier is ready.
"""

import hashlib
from dataclasses import dataclass
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IntakeBufferItem, IntakePurpose, IntakeSource
from app.db.repositories.intake_repo import IntakeRepo
from app.errors import Conflict, NotFound, Validation
from app.logging import get_logger
from app.services.intake_extractors import UnsupportedFormat, registry
from app.storage.base import ObjectStore, workspace_key

log = get_logger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB (LLD §C2)


@dataclass
class SubmissionResult:
    item: IntakeBufferItem
    deduped: bool  # True if SHA matched an existing item


class IntakeProcessor:
    def __init__(self, session: AsyncSession, storage: ObjectStore) -> None:
        self.session = session
        self.storage = storage
        self.repo = IntakeRepo(session)

    # ---------------- Submission ----------------

    async def submit_text(
        self,
        *,
        workspace_id: UUID,
        organization_id: UUID,
        submitted_by_user_id: UUID,
        purpose: IntakePurpose,
        text: str,
        source: IntakeSource = "form",
    ) -> SubmissionResult:
        if not text.strip():
            raise Validation("text content cannot be empty")
        item = await self.repo.create(
            workspace_id=workspace_id,
            organization_id=organization_id,
            submitted_by_user_id=submitted_by_user_id,
            source=source,
            purpose=purpose,
            content_text=text,
            content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        await self.session.commit()
        # NB: actual classification + handler dispatch is enqueued for the worker
        # in Chunk 3. For Chunk 2 the item lands queued.
        return SubmissionResult(item=item, deduped=False)

    async def submit_upload(
        self,
        *,
        workspace_id: UUID,
        organization_id: UUID,
        submitted_by_user_id: UUID,
        purpose: IntakePurpose,
        blob: BinaryIO,
        filename: str,
        content_mime: str | None,
    ) -> SubmissionResult:
        data = blob.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise Validation(
                f"upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
                details={"size_bytes": len(data)},
            )

        sha = hashlib.sha256(data).hexdigest()
        existing = await self.repo.find_by_sha(workspace_id, sha)
        if existing is not None:
            return SubmissionResult(item=existing, deduped=True)

        # Resolve extractor BEFORE upload so we fail fast on unsupported types
        try:
            extractor = registry.resolve(content_mime, filename)
        except UnsupportedFormat as e:
            raise Validation(str(e), details={"filename": filename, "mime": content_mime}) from e

        # Stage the item so we have an id for the key
        item_id = uuid4()
        key = workspace_key(workspace_id, "intake", str(item_id), filename)

        # Upload the blob
        await self.storage.put(key, data, content_mime or "application/octet-stream")

        # Persist the row
        item = await self.repo.create(
            workspace_id=workspace_id,
            organization_id=organization_id,
            submitted_by_user_id=submitted_by_user_id,
            source="upload",
            purpose=purpose,
            content_blob_key=key,
            content_mime=content_mime,
            content_filename=filename,
            content_sha256=sha,
        )
        await self.repo.update_status(item.id, extractor_used=extractor.name)
        await self.session.commit()
        return SubmissionResult(item=item, deduped=False)

    # ---------------- Inspection ----------------

    async def get(self, item_id: UUID) -> IntakeBufferItem:
        item = await self.repo.get(item_id)
        if item is None:
            raise NotFound(f"intake item {item_id} not found")
        return item

    async def list(
        self,
        workspace_id: UUID,
        *,
        purpose: IntakePurpose | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[IntakeBufferItem]:
        return await self.repo.list_for_workspace(workspace_id, purpose=purpose, limit=limit, offset=offset)

    async def download_url(self, item: IntakeBufferItem, *, ttl_seconds: int = 900) -> str:
        if not item.content_blob_key:
            raise Validation("item has no uploaded blob")
        return await self.storage.signed_url(item.content_blob_key, ttl_seconds=ttl_seconds, method="GET")

    # ---------------- Mutation ----------------

    async def supersede(self, *, old_item_id: UUID, new_item_id: UUID) -> None:
        old = await self.repo.get(old_item_id)
        if old is None:
            raise NotFound(f"intake item {old_item_id} not found")
        if old.status == "superseded":
            raise Conflict(
                "item already superseded", details={"head_item_id": str(old.superseded_by_item_id)}
            )
        new = await self.repo.get(new_item_id)
        if new is None:
            raise NotFound(f"intake item {new_item_id} not found")
        if new.workspace_id != old.workspace_id:
            raise Validation("cannot supersede across workspaces")
        await self.repo.mark_superseded(old_item_id, new_item_id)
        await self.session.commit()

    async def soft_delete(self, item_id: UUID, *, force: bool = False) -> None:
        item = await self.repo.get(item_id)
        if item is None:
            raise NotFound(f"intake item {item_id} not found")
        # Linkage check lands with §C8 (we don't have brain pages yet, so always OK)
        _ = force  # placeholder
        if item.content_blob_key:
            try:
                await self.storage.delete(item.content_blob_key)
            except Exception:
                log.warning("storage_delete_failed", key=item.content_blob_key, item_id=str(item_id))
        await self.repo.soft_delete(item_id)
        await self.session.commit()
