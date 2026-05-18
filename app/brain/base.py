"""BrainProvider abstract base.

Phase 0 §C8 ships:
  - ensure_schema:       creates brain_w_{wid} + brain_pages + brain_page_versions
  - get_page:            current truth + timeline for one slug
  - upsert_page:         insert-or-update with provenance + version chain
  - append_timeline:     add an event entry without touching compiled_truth
  - list_versions:       version history for one slug
  - soft_delete_page:    mark deleted_at; rows retained for audit
  - hybrid_search:       returns [] in Phase 0; §D3 lands RRF + backlink-boost

manager_authoritative enforcement (HLD §9.6): once a Manager has corrected a
field, the auto-extractor cannot silently overwrite it. The upsert_page path
raises ManagerAuthoritativeConflict when a non-manager_authoritative write
targets a manager_authoritative page; correction-driven writes set
manager_authoritative=True and proceed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

# Typed-graph edge kinds emitted by brain_updater (Phase 1 §F4).
BrainEdgeType = str  # alias for clarity; allowed values:
ALLOWED_EDGE_TYPES = ("mentioned_in", "works_at", "attended", "discussed")


@dataclass(frozen=True)
class BrainSearchHit:
    slug: str
    title: str
    snippet: str
    score: float


@dataclass(frozen=True)
class TimelineEntry:
    ts: datetime
    text: str
    provenance_id: UUID | None
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BrainPageSnapshot:
    slug: str
    kind: str  # account, person, product, theme, ...
    title: str
    compiled_truth: str
    timeline: list[dict[str, Any]]
    tags: list[str]
    provenance_id: UUID | None
    manager_authoritative: bool
    deleted_at: datetime | None
    version: int
    updated_at: datetime


@dataclass(frozen=True)
class BrainPageVersionSnapshot:
    id: UUID
    slug: str
    version: int
    compiled_truth: str
    provenance_id: UUID | None
    superseded_by: UUID | None
    created_at: datetime


class ManagerAuthoritativeConflict(Exception):
    """Raised when a non-correction write targets a page the Manager has
    corrected. Caller should surface to NeedsReview rather than silently
    overwrite.
    """

    def __init__(self, slug: str, attempted_kind: str = "automated_extraction") -> None:
        super().__init__(f"page {slug!r} is manager-authoritative; refusing {attempted_kind} write")
        self.slug = slug
        self.attempted_kind = attempted_kind


class BrainProvider(ABC):
    @abstractmethod
    async def ensure_schema(self, workspace_id: UUID) -> None: ...

    @abstractmethod
    async def get_page(self, workspace_id: UUID, slug: str) -> BrainPageSnapshot | None: ...

    @abstractmethod
    async def upsert_page(
        self,
        workspace_id: UUID,
        *,
        slug: str,
        kind: str,
        title: str,
        compiled_truth: str,
        provenance_id: UUID,
        manager_authoritative: bool = False,
        tags: list[str] | None = None,
        timeline_seed: TimelineEntry | None = None,
    ) -> BrainPageSnapshot:
        """Insert-or-update with versioning.

        On update:
          - If existing page is manager_authoritative AND manager_authoritative
            on this call is False -> raise ManagerAuthoritativeConflict.
          - Else: create a new BrainPageVersion row (monotonic version) for
            the prior compiled_truth, mark it superseded_by=new_version_id,
            and set the page's compiled_truth + new provenance.
        """

    @abstractmethod
    async def append_timeline(
        self,
        workspace_id: UUID,
        *,
        slug: str,
        entry: TimelineEntry,
    ) -> BrainPageSnapshot:
        """Append a timeline entry. Does NOT change compiled_truth."""

    @abstractmethod
    async def list_versions(self, workspace_id: UUID, slug: str) -> list[BrainPageVersionSnapshot]: ...

    @abstractmethod
    async def soft_delete_page(self, workspace_id: UUID, slug: str) -> None: ...

    async def update_tags(
        self, workspace_id: UUID, slug: str, tags: list[str]
    ) -> None:
        """Replace the page's tags list. Default no-op so non-overriding providers don't break.

        Phase 1 §F4: web-verifier-driven tag application calls this rather
        than threading tag merges through upsert_page (which would force a
        new version-row on every tag update).
        """
        del workspace_id, slug, tags

    @abstractmethod
    async def hybrid_search(
        self,
        workspace_id: UUID,
        query: str,
        *,
        k: int = 8,
        types: list[str] | None = None,
    ) -> list[BrainSearchHit]:
        """Empty until §D3 lands RRF + backlink-boost."""

    async def traverse(
        self,
        workspace_id: UUID,
        slug: str,
        *,
        depth: int = 2,
        edge_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Typed-graph traversal over BrainEdge rows (Phase 1 §F4).

        Default implementation returns []; PostgresBrainProvider overrides.
        """
        del workspace_id, slug, depth, edge_types
        return []
