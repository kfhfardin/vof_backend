"""CallerMemoryProvider abstract base.

Per-caller memory isolation uses Supermemory's `containerTags` pattern
(https://supermemory.ai/docs/). Each memory carries one or more tags;
search filters by tag. We always tag with at least:

    [f"caller_{field_employee_id}", f"workspace_{workspace_id}"]

  - `caller_{field_employee_id}` is the primary isolation tag (one Field Rep
    per tag = "one user per container" in Supermemory's terms).
  - `workspace_{workspace_id}` is the secondary tag so a workspace-wide
    search (analytics, deletion-on-Workspace-delete) hits every caller's
    memories at once.

Implementations:
  - StubCallerMemoryProvider (app/memory/stub.py) - Phase 0 dev/test
  - SupermemoryCallerMemoryProvider (app/memory/supermemory.py) - production
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class CallerMemoryHit:
    id: str
    content: str
    score: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class CallerProfile:
    """Supermemory's aggregate profile for one caller. `summary` is a
    short LLM-generated paragraph extracted from the caller's memories."""

    container_tag: str
    summary: str
    facts: dict[str, Any]


def container_tags_for(workspace_id: UUID, field_employee_id: UUID) -> list[str]:
    """Canonical container tags for a (workspace, caller) pair."""
    return [f"caller_{field_employee_id}", f"workspace_{workspace_id}"]


def caller_tag(field_employee_id: UUID) -> str:
    """The primary per-caller isolation tag - used in get_profile + as the
    join key for per-caller searches."""
    return f"caller_{field_employee_id}"


def workspace_tag(workspace_id: UUID) -> str:
    """Workspace-wide tag - used for workspace-scoped queries + bulk deletes."""
    return f"workspace_{workspace_id}"


class CallerMemoryProvider(ABC):
    @abstractmethod
    async def ensure_namespace(self, workspace_id: UUID) -> None:
        """Set up any per-Workspace state. Supermemory: noop."""

    @abstractmethod
    async def add(
        self,
        *,
        container_tags: list[str],
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist a memory. Returns the provider-assigned memory id."""

    @abstractmethod
    async def search(
        self,
        *,
        container_tags: list[str],
        query: str,
        k: int = 5,
    ) -> list[CallerMemoryHit]:
        """Semantic search filtered by container_tags.

        Provider AND-matches: a memory must carry every tag in
        `container_tags` to be returned. Pass `[caller_{feid}]` for
        per-caller results; pass `[workspace_{wid}]` for workspace-wide.
        """

    @abstractmethod
    async def get_profile(self, container_tag: str) -> CallerProfile | None:
        """Aggregate profile (Supermemory's profile endpoint).

        Takes a single tag (not a list) because Supermemory builds the
        profile per-container.
        """

    @abstractmethod
    async def delete(self, *, container_tag: str, memory_id: str) -> None:
        """Delete a single memory.

        Supermemory requires the container_tag along with the id (it uses
        `memories.forget(container_tag, id)`). Pass the caller's primary
        tag (`caller_<field_employee_id>`).
        """
