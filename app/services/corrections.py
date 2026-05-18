"""CorrectionService - Manager-driven overrides.

Per HLD §9.2 / LLD §C8: a Manager correction always wins. It overwrites
the current compiled_truth, retains the prior version on the chain (so the
audit trail is intact), marks the page manager_authoritative=True so the
auto-extractor can't silently undo it, and enqueues correction_cascade for
downstream cleanup.

Phase 0 ships three correction kinds (the minimum for the demo):
  - replace_compiled_truth
  - soft_delete_page
  - append_timeline_entry  (the lightest weight - no version change)

The bigger kinds (merge_entities, split_entity, delete_edge, add_edge,
set_profile_field) need §D3 typed graph + caller_profiles tables; they
extend this service without re-shaping the contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.base import BrainPageSnapshot, BrainProvider, TimelineEntry
from app.db.repositories.provenance_repo import ProvenanceRepo
from app.errors import NotFound, Validation
from app.logging import get_logger

log = get_logger(__name__)


class CorrectionKind(StrEnum):
    REPLACE_COMPILED_TRUTH = "replace_compiled_truth"
    SOFT_DELETE_PAGE = "soft_delete_page"
    APPEND_TIMELINE_ENTRY = "append_timeline_entry"


class CorrectionService:
    def __init__(self, session: AsyncSession, brain: BrainProvider) -> None:
        self.session = session
        self.brain = brain
        self.provenance_repo = ProvenanceRepo(session)

    async def apply(
        self,
        *,
        workspace_id: UUID,
        target_slug: str,
        kind: CorrectionKind | str,
        payload: dict[str, Any],
        rationale: str | None,
        corrected_by_user_id: UUID,
    ) -> BrainPageSnapshot | None:
        try:
            kind_enum = CorrectionKind(kind)
        except ValueError as e:
            raise Validation(
                f"unsupported correction kind: {kind!r}",
                details={"supported": [k.value for k in CorrectionKind]},
            ) from e

        page = await self.brain.get_page(workspace_id, target_slug)
        if page is None and kind_enum is not CorrectionKind.REPLACE_COMPILED_TRUTH:
            raise NotFound(f"brain page {target_slug!r} not found")

        # Provenance: always source_type=manager_correction, confidence=1.0.
        provenance = await self.provenance_repo.create(
            workspace_id=workspace_id,
            source_type="manager_correction",
            source_id=None,
            extracted_by=str(corrected_by_user_id),
            confidence=1.0,
            rationale=rationale,
            cites=[{"prior_provenance_id": str(page.provenance_id)}] if page and page.provenance_id else [],
        )
        await self.session.commit()

        now = datetime.now(UTC)

        if kind_enum is CorrectionKind.REPLACE_COMPILED_TRUTH:
            new_truth = str(payload.get("compiled_truth") or "").strip()
            if not new_truth:
                raise Validation("replace_compiled_truth requires non-empty compiled_truth")
            kind_str = str(payload.get("kind") or (page.kind if page else "misc"))
            title = str(payload.get("title") or (page.title if page else target_slug))
            audit_text = "[CORRECTED by manager]"
            if page is not None:
                audit_text += f" Previously: {page.compiled_truth[:200]!r}."
            if rationale:
                audit_text += f" Reason: {rationale!r}."
            audit_text += f" See correction provenance {provenance.id}."

            snapshot = await self.brain.upsert_page(
                workspace_id,
                slug=target_slug,
                kind=kind_str,
                title=title,
                compiled_truth=new_truth,
                provenance_id=provenance.id,
                manager_authoritative=True,
                tags=page.tags if page else [],
                timeline_seed=TimelineEntry(
                    ts=now,
                    text=audit_text,
                    provenance_id=provenance.id,
                    tags=["correction", "manager_authoritative"],
                ),
            )
            await _enqueue_cascade(workspace_id=workspace_id, slug=target_slug, kind=kind_enum.value)
            return snapshot

        if kind_enum is CorrectionKind.SOFT_DELETE_PAGE:
            assert page is not None
            # First append an audit entry, then soft-delete.
            await self.brain.append_timeline(
                workspace_id,
                slug=target_slug,
                entry=TimelineEntry(
                    ts=now,
                    text=f"[DELETED by manager] Reason: {rationale or '(none)'}. "
                    f"Correction provenance {provenance.id}.",
                    provenance_id=provenance.id,
                    tags=["correction", "soft_delete"],
                ),
            )
            await self.brain.soft_delete_page(workspace_id, target_slug)
            await _enqueue_cascade(workspace_id=workspace_id, slug=target_slug, kind=kind_enum.value)
            return await self.brain.get_page(workspace_id, target_slug)

        if kind_enum is CorrectionKind.APPEND_TIMELINE_ENTRY:
            assert page is not None
            text_payload = str(payload.get("text") or "").strip()
            if not text_payload:
                raise Validation("append_timeline_entry requires non-empty text")
            snapshot = await self.brain.append_timeline(
                workspace_id,
                slug=target_slug,
                entry=TimelineEntry(
                    ts=now,
                    text=f"[NOTE by manager] {text_payload}",
                    provenance_id=provenance.id,
                    tags=["correction", "note"],
                ),
            )
            # No cascade for note-only corrections.
            return snapshot

        # Unreachable given the enum guard above.
        raise Validation(f"unsupported correction kind: {kind!r}")


async def _enqueue_cascade(*, workspace_id: UUID, slug: str, kind: str) -> None:
    """Fire-and-forget enqueue of the cascade worker.

    Uses test-mode short-circuit (CORRECTION_CASCADE_INLINE) so tests don't
    need an arq worker running.
    """
    from app.workers.correction_cascade import schedule_or_inline

    try:
        await schedule_or_inline(workspace_id=workspace_id, slug=slug, kind=kind)
    except Exception:
        log.exception(
            "correction_cascade_schedule_failed",
            workspace_id=str(workspace_id),
            slug=slug,
            kind=kind,
        )
