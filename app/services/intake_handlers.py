"""Typed intake handlers - dispatched by IntakeProcessor on (scope, kind).

§C8 promotes these from "record planned writes" to "actually call the
brain provider". Each handler:

  1. Creates a Provenance row tagged source_type=automated_extraction
     (or the original IntakeBufferItem.source_type for Manager-driven
     uploads/forms).
  2. Calls brain.upsert_page or brain.append_timeline as appropriate.
  3. If the target page is manager_authoritative, catches
     ManagerAuthoritativeConflict and returns a needs_review result so
     the IntakeProcessor flips item status accordingly.
  4. Returns a handler_result blob with the slugs / entries written +
     provenance id (the persistent audit trail).

Real Brain page upserts now happen here. The CallerBrain / Supermemory
side still lands with §C11 (CallerBrainHandler still records intent only
since FieldEmployee per-Workspace `caller_profiles` writes need §C11's
Supermemory adapter for the free-form part).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.brain.base import (
    BrainProvider,
    ManagerAuthoritativeConflict,
    TimelineEntry,
)
from app.db.app_session import app_session
from app.db.repositories.provenance_repo import ProvenanceRepo
from app.logging import get_logger

log = get_logger(__name__)


@dataclass
class HandlerInput:
    workspace_id: UUID
    organization_id: UUID
    item_id: UUID
    content_text: str | None
    classification: dict[str, Any]


class IntakeHandler(Protocol):
    name: str

    async def ingest(self, inputs: HandlerInput, *, brain: BrainProvider) -> dict[str, Any]: ...


_SLUG_CHARS = re.compile(r"[^a-z0-9-_]+")
_KIND_TO_SLUG_PREFIX: dict[str, str] = {
    "account": "accounts",
    "person": "people",
    "product": "products",
    "playbook": "playbooks",
    "theme": "themes",
    "org_positioning": "org",
}


def _slugify(text: str) -> str:
    s = text.strip().lower().replace(" ", "-")
    s = _SLUG_CHARS.sub("", s)
    return s.strip("-") or "untitled"


def _derive_slug(classification: dict[str, Any], item_id: UUID) -> str:
    suggested = classification.get("suggested_slug")
    if isinstance(suggested, str) and suggested.strip():
        return suggested.strip().lower()
    kind = classification.get("kind", "misc")
    prefix = _KIND_TO_SLUG_PREFIX.get(str(kind), str(kind))
    # Try to pull a name from extracted_entities first; fall back to item id suffix
    entities = classification.get("extracted_entities") or []
    if entities and isinstance(entities[0], dict):
        name = entities[0].get("name")
        if name:
            return f"{prefix}/{_slugify(str(name))}"
    return f"{prefix}/{item_id.hex[:8]}"


def _derive_title(classification: dict[str, Any], slug: str) -> str:
    entities = classification.get("extracted_entities") or []
    if entities and isinstance(entities[0], dict):
        name = entities[0].get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    # Slug last segment as title fallback
    return slug.split("/")[-1].replace("-", " ").title()


def _compiled_truth_seed(content_text: str | None) -> str:
    if not content_text:
        return ""
    # Take the first 600 chars; the brain page is the gist, not the archive.
    snippet = content_text.strip()
    return snippet[:600]


# ---------------- Handlers ----------------


class OrgBrainHandler:
    """ORG_WIDE items - account / product / playbook / theme / org_positioning."""

    name = "org_brain"

    async def ingest(self, inputs: HandlerInput, *, brain: BrainProvider) -> dict[str, Any]:
        cl = inputs.classification
        slug = _derive_slug(cl, inputs.item_id)
        title = _derive_title(cl, slug)
        compiled = _compiled_truth_seed(inputs.content_text)

        async with app_session() as session:
            prov_repo = ProvenanceRepo(session)
            provenance = await prov_repo.create(
                workspace_id=inputs.workspace_id,
                source_type="automated_extraction",
                source_id=inputs.item_id,
                extracted_by=f"classifier@{cl.get('extracted_by', 'unknown')}",
                confidence=cl.get("confidence"),
                rationale=cl.get("reasoning"),
            )
            await session.commit()
            provenance_id = provenance.id

        timeline_seed = TimelineEntry(
            ts=datetime.now(UTC),
            text=f"Captured during intake (item {inputs.item_id})",
            provenance_id=provenance_id,
            tags=["intake"],
        )
        try:
            snapshot = await brain.upsert_page(
                inputs.workspace_id,
                slug=slug,
                kind=str(cl.get("kind", "misc")),
                title=title,
                compiled_truth=compiled,
                provenance_id=provenance_id,
                manager_authoritative=False,
                tags=[],
                timeline_seed=timeline_seed,
            )
        except ManagerAuthoritativeConflict:
            # Append a timeline entry so we don't lose the signal, but don't
            # overwrite compiled_truth. The Manager will see the new info in
            # the timeline + the NeedsReview surface.
            await brain.append_timeline(
                inputs.workspace_id,
                slug=slug,
                entry=TimelineEntry(
                    ts=datetime.now(UTC),
                    text=(
                        f"[CONFLICT] auto-extraction wanted to update this page (item "
                        f"{inputs.item_id}) but the Manager has it locked. Review needed."
                    ),
                    provenance_id=provenance_id,
                    tags=["needs_review", "manager_authoritative_conflict"],
                ),
            )
            return {
                "handler": self.name,
                "action": "manager_authoritative_conflict",
                "slug": slug,
                "provenance_id": str(provenance_id),
                "needs_review": True,
            }

        return {
            "handler": self.name,
            "action": "upserted_brain_page",
            "slug": snapshot.slug,
            "kind": snapshot.kind,
            "version": snapshot.version,
            "extracted_entities": cl.get("extracted_entities", []),
            "provenance_id": str(provenance_id),
        }


class CallerBrainHandler:
    """CALLER_SPECIFIC items - caller_identity / caller_style.

    Still records-only in Phase 0 §C8: writes to FieldEmployee.profile JSON
    and Supermemory land with §C11. Provenance is still created so the
    audit chain is intact when §C11 wires the rest.
    """

    name = "caller_brain"

    async def ingest(self, inputs: HandlerInput, *, brain: BrainProvider) -> dict[str, Any]:
        cl = inputs.classification
        async with app_session() as session:
            prov_repo = ProvenanceRepo(session)
            provenance = await prov_repo.create(
                workspace_id=inputs.workspace_id,
                source_type="automated_extraction",
                source_id=inputs.item_id,
                confidence=cl.get("confidence"),
                rationale=cl.get("reasoning"),
            )
            await session.commit()
            provenance_id = provenance.id
        return {
            "handler": self.name,
            "action": "queued_caller_profile_update",
            "target_caller_id": cl.get("target_caller_id"),
            "kind": cl.get("kind"),
            "provenance_id": str(provenance_id),
        }


class CrossRefHandler:
    """BOTH items - ownership assignments. Phase 0: upsert the Workspace-side
    page; the directed BrainEdge graph lands with §D3."""

    name = "cross_ref"

    async def ingest(self, inputs: HandlerInput, *, brain: BrainProvider) -> dict[str, Any]:
        # The Workspace-side page is the load-bearing write; reuse OrgBrain.
        org_result = await OrgBrainHandler().ingest(inputs, brain=brain)
        return {
            "handler": self.name,
            "action": "upserted_workspace_side",
            "workspace_side": org_result,
            "target_caller_id": inputs.classification.get("target_caller_id"),
            "note": "directed BrainEdge graph lands with §D3",
        }


class RawSourceHandler:
    """RAW_SOURCE items - documents. Phase 0 §C8: upsert one brain page per
    extracted entity (capped) + record the document reference. The full
    fan-out (whole-doc Supermemory push + brain_seeder row-walk) lands §C11.
    """

    name = "raw_source"

    async def ingest(self, inputs: HandlerInput, *, brain: BrainProvider) -> dict[str, Any]:
        cl = inputs.classification
        async with app_session() as session:
            prov_repo = ProvenanceRepo(session)
            provenance = await prov_repo.create(
                workspace_id=inputs.workspace_id,
                source_type="automated_extraction",
                source_id=inputs.item_id,
                confidence=cl.get("confidence"),
                rationale=cl.get("reasoning"),
            )
            await session.commit()
            provenance_id = provenance.id

        entities = cl.get("extracted_entities") or []
        written: list[str] = []
        for ent in entities[:25]:  # cap for Phase 0
            if not isinstance(ent, dict):
                continue
            name = ent.get("name")
            kind_raw = str(ent.get("type", "misc"))
            if not name:
                continue
            prefix = _KIND_TO_SLUG_PREFIX.get(kind_raw, kind_raw)
            slug = f"{prefix}/{_slugify(str(name))}"
            try:
                snap = await brain.upsert_page(
                    inputs.workspace_id,
                    slug=slug,
                    kind=kind_raw,
                    title=str(name),
                    compiled_truth=f"Extracted from raw source (item {inputs.item_id}).",
                    provenance_id=provenance_id,
                    manager_authoritative=False,
                    timeline_seed=TimelineEntry(
                        ts=datetime.now(UTC),
                        text=f"Seen in raw source (item {inputs.item_id})",
                        provenance_id=provenance_id,
                        tags=["raw_source"],
                    ),
                )
                written.append(snap.slug)
            except ManagerAuthoritativeConflict:
                await brain.append_timeline(
                    inputs.workspace_id,
                    slug=slug,
                    entry=TimelineEntry(
                        ts=datetime.now(UTC),
                        text=f"[CONFLICT] raw source mentioned {name} (item {inputs.item_id})",
                        provenance_id=provenance_id,
                        tags=["needs_review", "manager_authoritative_conflict"],
                    ),
                )

        return {
            "handler": self.name,
            "action": "fanout_raw_source",
            "pages_upserted": written,
            "extracted_entities_count": len(entities),
            "provenance_id": str(provenance_id),
            "note": "Supermemory whole-doc push + brain_seeder enqueue land with §C11",
        }


_HANDLERS: dict[str, IntakeHandler] = {
    "ORG_WIDE": OrgBrainHandler(),
    "CALLER_SPECIFIC": CallerBrainHandler(),
    "BOTH": CrossRefHandler(),
    "RAW_SOURCE": RawSourceHandler(),
}


def resolve_handler(scope: str) -> IntakeHandler:
    if scope not in _HANDLERS:
        raise ValueError(f"unknown scope {scope!r}; expected one of {sorted(_HANDLERS)}")
    return _HANDLERS[scope]
