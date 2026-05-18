"""Stub CallerMemoryProvider for dev + tests.

Returns empty results on search/profile and accepts add() as a noop.
Production deployments bind SupermemoryCallerMemoryProvider via the deps
factory; this stub is only used when SUPERMEMORY_API_KEY is empty.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.memory.base import CallerMemoryHit, CallerMemoryProvider, CallerProfile


class StubCallerMemoryProvider(CallerMemoryProvider):
    async def ensure_namespace(self, workspace_id: UUID) -> None:
        return None

    async def add(
        self,
        *,
        container_tags: list[str],
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        # Return a synthetic id so callers can log it; nothing persisted.
        return f"stub_{uuid4().hex[:12]}"

    async def search(
        self,
        *,
        container_tags: list[str],
        query: str,
        k: int = 5,
    ) -> list[CallerMemoryHit]:
        return []

    async def get_profile(self, container_tag: str) -> CallerProfile | None:
        return None

    async def delete(self, *, container_tag: str, memory_id: str) -> None:
        return None
