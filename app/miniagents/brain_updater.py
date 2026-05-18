"""brain_updater mini-agent - the per-call compounding step.

Phase 0 §C11 minimum (per LLD):
  1. For each extracted entity:
       - resolve slug (use slug_hint if present, else derive from kind+name)
       - get_page(slug)
         - if exists: append a TimelineEntry citing this call - do NOT touch compiled_truth
         - if absent: upsert a stub page (compiled_truth = "Mentioned in call <id>...")
  2. Provenance carries source_type=automated_extraction, source_id=call_id,
     extracted_by="summarizer@<version>".
  3. manager_authoritative conflicts (the brain provider raises) get a
     timeline entry tagged needs_review instead - the Manager sees the
     signal without it overwriting their corrected page.

Phase 1 §F4 extension: accepts an optional `verdicts` kwarg on
BrainUpdateInput (back-compat: callers that don't pass verdicts keep
working). When a verdict's claim_subject matches a page slug being
written, the page is tagged with the appropriate trust marker
(WEB_CORROBORATED / UNVERIFIED_WEB / CONTRADICTS_WEB_SOURCE).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.brain.base import BrainProvider, ManagerAuthoritativeConflict, TimelineEntry
from app.brain.tags import (
    CONTRADICTS_WEB_SOURCE,
    UNVERIFIED_WEB,
    WEB_CORROBORATED,
)
from app.db.app_session import app_session
from app.db.repositories.provenance_repo import ProvenanceRepo
from app.logging import get_logger
from app.miniagents.summarizer_agent import SummarizerOutput

log = get_logger(__name__)

_SLUG_CHARS = re.compile(r"[^a-z0-9-_]+")
_KIND_TO_SLUG_PREFIX: dict[str, str] = {
    "person": "people",
    "company": "accounts",
    "account": "accounts",
    "product": "products",
    "theme": "themes",
}


def _slugify(text: str) -> str:
    s = text.strip().lower().replace(" ", "-")
    s = _SLUG_CHARS.sub("", s)
    return s.strip("-") or "untitled"


def _resolve_slug(entity: dict[str, Any]) -> str:
    hint = entity.get("slug_hint")
    if hint:
        return str(hint).strip().lower()
    kind = str(entity.get("type", "misc"))
    name = str(entity.get("name", "untitled"))
    prefix = _KIND_TO_SLUG_PREFIX.get(kind, kind)
    return f"{prefix}/{_slugify(name)}"


@dataclass(frozen=True)
class BrainUpdateInput:
    workspace_id: UUID
    call_id: UUID
    summary: SummarizerOutput
    # Phase 1 §F4: optional web-verifier verdicts. When provided, pages
    # whose slug corresponds to a verdict's claim_subject get tagged.
    # Each verdict is a dict shaped {claim_subject, status, ...}.
    verdicts: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class BrainUpdateResult:
    pages_upserted: list[str]
    timeline_appends: list[str]
    needs_review: list[str]
    tags_applied: dict[str, list[str]] = field(default_factory=dict)


def _verdict_tag(status: str, existing_tags: list[str]) -> str | None:
    """Map verifier status -> reserved BrainPage tag. None if no tag should be applied.

    `unconfirmed` only emits `unverified_web` when the page doesn't already
    carry another web tag - per LLD F4 spec.
    """
    if status == "corroborated":
        return WEB_CORROBORATED
    if status == "contradicted":
        return CONTRADICTS_WEB_SOURCE
    if status == "unconfirmed":
        web_tags_present = {WEB_CORROBORATED, CONTRADICTS_WEB_SOURCE} & set(existing_tags)
        if not web_tags_present:
            return UNVERIFIED_WEB
    return None


def _build_verdict_index(verdicts: list[dict[str, Any]] | None) -> dict[str, str]:
    """Map slug-ish claim_subject -> status. Subjects are slugged to match page slugs."""
    if not verdicts:
        return {}
    out: dict[str, str] = {}
    for v in verdicts:
        if not isinstance(v, dict):
            continue
        subject = str(v.get("claim_subject") or "").strip()
        status = str(v.get("status") or "").strip().lower()
        if not subject or status not in {"corroborated", "unconfirmed", "contradicted"}:
            continue
        # Index under both the raw subject and a normalized variant so
        # downstream lookups can match against either page slugs or names.
        key_raw = subject.lower()
        key_slug = _slugify(subject)
        out.setdefault(key_raw, status)
        out.setdefault(key_slug, status)
    return out


async def run_brain_updater(
    inputs: BrainUpdateInput,
    *,
    brain: BrainProvider,
) -> BrainUpdateResult:
    summary = inputs.summary
    entities = list(summary.extracted_entities or [])

    pages_upserted: list[str] = []
    timeline_appends: list[str] = []
    needs_review: list[str] = []

    verdict_index = _build_verdict_index(inputs.verdicts)
    tags_applied: dict[str, list[str]] = {}

    if not entities and not verdict_index:
        log.info("brain_updater_no_entities", call_id=str(inputs.call_id))
        return BrainUpdateResult(pages_upserted, timeline_appends, needs_review)

    # One provenance row per call covers every page touched (per-page rather
    # than per-entity for Phase 0 - keeps the provenance table compact).
    async with app_session() as session:
        prov_repo = ProvenanceRepo(session)
        prov = await prov_repo.create(
            workspace_id=inputs.workspace_id,
            source_type="field_call",
            source_id=inputs.call_id,
            extracted_by="summarizer@0.1.0",
            confidence=None,
            rationale=summary.discussion[:300],
        )
        await session.commit()
        provenance_id = prov.id

    now = datetime.now(UTC)

    for ent in entities:
        if not isinstance(ent, dict) or not ent.get("name"):
            continue
        slug = _resolve_slug(ent)
        kind = str(ent.get("type", "misc"))
        name = str(ent.get("name", "")).strip()

        existing = await brain.get_page(inputs.workspace_id, slug)
        timeline_text = f"Mentioned in call {inputs.call_id}: {summary.discussion[:200]}"

        if existing is None:
            # Create stub page
            try:
                snap = await brain.upsert_page(
                    inputs.workspace_id,
                    slug=slug,
                    kind=kind,
                    title=name,
                    compiled_truth=(
                        f"Stub page seeded from call {inputs.call_id}. Auto-extracted; awaiting enrichment."
                    ),
                    provenance_id=provenance_id,
                    manager_authoritative=False,
                    timeline_seed=TimelineEntry(
                        ts=now,
                        text=timeline_text,
                        provenance_id=provenance_id,
                        tags=["from_call"],
                    ),
                )
                pages_upserted.append(snap.slug)
            except ManagerAuthoritativeConflict:
                # Shouldn't happen on a stub - the page didn't exist - but
                # defensive in case of race with another worker.
                needs_review.append(slug)
            continue

        # Existing page: append timeline only. Do NOT touch compiled_truth.
        try:
            await brain.append_timeline(
                inputs.workspace_id,
                slug=slug,
                entry=TimelineEntry(
                    ts=now,
                    text=timeline_text,
                    provenance_id=provenance_id,
                    tags=["from_call"],
                ),
            )
            timeline_appends.append(slug)
        except Exception:
            log.exception(
                "brain_updater_timeline_append_failed",
                slug=slug,
                call_id=str(inputs.call_id),
            )

    # Phase 1 §F4: apply verifier trust tags to any matching page.
    # Match a verdict to a page by trying both the raw slug and a slug
    # derived from the subject; this catches person/account pages that
    # were created above with kind-prefixed slugs.
    if verdict_index:
        # Build a set of (raw, slugified) candidate keys for each page we
        # know about so we can map verdicts -> page slugs. We re-read the
        # touched pages to learn their full current tag list.
        touched_slugs = list({*pages_upserted, *timeline_appends})
        # Also accept any verdict subjects that exactly match a slug we just touched.
        for slug in touched_slugs:
            snap = await brain.get_page(inputs.workspace_id, slug)
            if snap is None:
                continue
            subj_keys = {slug.lower(), _slugify(snap.title), snap.title.lower()}
            status = next(
                (verdict_index[k] for k in subj_keys if k in verdict_index), None
            )
            if status is None:
                continue
            new_tag = _verdict_tag(status, list(snap.tags))
            if new_tag is None or new_tag in snap.tags:
                continue
            merged_tags = [*snap.tags, new_tag]
            try:
                await brain.update_tags(inputs.workspace_id, slug, merged_tags)
                tags_applied.setdefault(slug, []).append(new_tag)
            except Exception:
                log.exception(
                    "brain_updater_tag_apply_failed",
                    slug=slug,
                    tag=new_tag,
                    call_id=str(inputs.call_id),
                )

    return BrainUpdateResult(
        pages_upserted=pages_upserted,
        timeline_appends=timeline_appends,
        needs_review=needs_review,
        tags_applied=tags_applied,
    )


class BrainUpdater:
    """Class facade for callers that prefer DI."""

    name = "brain_updater"

    async def run(self, inputs: BrainUpdateInput, *, brain: BrainProvider) -> BrainUpdateResult:
        return await run_brain_updater(inputs, brain=brain)
