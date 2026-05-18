"""SupermemoryCallerMemoryProvider - production adapter.

Wraps the `supermemory` SDK. Per-caller isolation via `containerTags`
(see app/memory/base.py for the tag scheme).

SDK methods used (verified against AsyncSupermemory in the installed
package - signatures pinned here so drift is caught explicitly):

  client.add(content=..., container_tags=..., metadata=...)
    -> AddResponse with .id  (and .status, typically "queued")

  client.search.documents(q=..., container_tags=..., limit=...)
    -> SearchDocumentsResponse with .results (list of items each with
       .document_id / .chunks[*].content / .score / .metadata).
       Note: top-level `id` and `content` are absent/null; use the
       document_id + chunk-content parsers in this module.

  client.profile(container_tag=..., q=...)
    -> ProfileResponse with .summary / .facts
    Note: this is a callable on the client, NOT client.profile.get().

  client.memories.forget(container_tag=..., id=...)
    -> MemoryForgetResponse
    The SDK has no `memories.delete`; forget IS the delete and it requires
    container_tag (Supermemory needs to know who is forgetting which memory).
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from app.logging import get_logger
from app.memory.base import CallerMemoryHit, CallerMemoryProvider, CallerProfile

log = get_logger(__name__)


def _build_async_client(api_key: str):  # type: ignore[no-untyped-def]
    """Construct an AsyncSupermemory. Kept free-standing so tests can
    monkeypatch a synthetic client in if they need to."""
    from supermemory import AsyncSupermemory

    return AsyncSupermemory(api_key=api_key)


def _coerce_str(value: Any) -> str:
    return str(value) if value is not None else ""


def _hit_id(item: Any) -> str:
    """Pull the memory id from a search-result item.

    Search results expose the id as `document_id` (and the camelCase alias
    `documentId`) — NOT `id`. The earlier `id` lookup silently returned ""
    on every result, so retrieved memories had no addressable identifier.
    """
    for attr in ("document_id", "documentId", "id"):
        val = getattr(item, attr, None)
        if val:
            return str(val)
    if isinstance(item, dict):
        for key in ("document_id", "documentId", "id"):
            val = item.get(key)
            if val:
                return str(val)
    return ""


def _hit_content(item: Any) -> str:
    """Pull the searchable text from a search-result item.

    Top-level `content` on a result is null; the real text lives in
    `chunks[0].content` (one item per matched chunk). Join all chunks so a
    multi-chunk match isn't truncated.
    """
    val = getattr(item, "content", None)
    if val is None and isinstance(item, dict):
        val = item.get("content") or item.get("text")
    if val:
        return _coerce_str(val)
    chunks = getattr(item, "chunks", None)
    if chunks is None and isinstance(item, dict):
        chunks = item.get("chunks")
    if chunks:
        parts: list[str] = []
        for ch in chunks:
            c = getattr(ch, "content", None) or (
                ch.get("content") if isinstance(ch, dict) else None
            )
            if c:
                parts.append(str(c))
        return "\n".join(parts)
    return ""


def _hit_score(item: Any) -> float:
    val = getattr(item, "score", None)
    if val is None and isinstance(item, dict):
        val = item.get("score") or item.get("relevance") or 0.0
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _hit_metadata(item: Any) -> dict[str, Any]:
    val = getattr(item, "metadata", None)
    if val is None and isinstance(item, dict):
        val = item.get("metadata") or {}
    if not isinstance(val, dict):
        return {}
    return dict(val)


class SupermemoryCallerMemoryProvider(CallerMemoryProvider):
    """Supermemory client.

    The AsyncSupermemory SDK is created **once per provider instance** and
    reused for every call. The previous per-call construction added an
    httpx pool + TLS handshake to every voice-turn retrieval and every
    post-call write. Lifespan shutdown calls close() to drain the SDK's
    underlying httpx pool gracefully.
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("SupermemoryCallerMemoryProvider requires a non-empty API key")
        self._api_key = api_key
        self._client_inst: Any = None
        self._init_lock = asyncio.Lock()

    async def _get_client(self) -> Any:
        if self._client_inst is not None:
            return self._client_inst
        async with self._init_lock:
            if self._client_inst is not None:
                return self._client_inst
            self._client_inst = _build_async_client(self._api_key)
        return self._client_inst

    async def close(self) -> None:
        """Drain the SDK's httpx pool. Called from FastAPI lifespan shutdown."""
        if self._client_inst is not None:
            close = getattr(self._client_inst, "aclose", None) or getattr(self._client_inst, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    log.exception("supermemory_client_close_failed")
            self._client_inst = None

    async def ensure_namespace(self, workspace_id: UUID) -> None:
        # Supermemory containers are implicit via containerTags - no setup needed.
        return None

    async def add(
        self,
        *,
        container_tags: list[str],
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        client = await self._get_client()
        try:
            result = await client.add(
                content=content,
                container_tags=container_tags,
                metadata=metadata or {},
            )
        except Exception:
            log.exception("supermemory_add_failed", container_tags=container_tags)
            raise
        memory_id = getattr(result, "id", None) or (result.get("id") if isinstance(result, dict) else None)
        return _coerce_str(memory_id)

    async def search(
        self,
        *,
        container_tags: list[str],
        query: str,
        k: int = 5,
    ) -> list[CallerMemoryHit]:
        client = await self._get_client()
        try:
            # `search.documents` is the documented per-user search method
            # (https://supermemory.ai/docs/) and supports `container_tags`
            # (plural) for multi-tag AND-filtering. `search.memories` only
            # supports the singular `container_tag` - not what we want.
            response = await client.search.documents(
                q=query,
                container_tags=container_tags,
                limit=k,
            )
        except Exception:
            log.exception("supermemory_search_failed", container_tags=container_tags, query=query)
            return []
        results = getattr(response, "results", None)
        if results is None and isinstance(response, dict):
            results = response.get("results") or []
        items = list(results or [])
        return [
            CallerMemoryHit(
                id=_hit_id(item),
                content=_hit_content(item),
                score=_hit_score(item),
                metadata=_hit_metadata(item),
            )
            for item in items
        ]

    async def get_profile(self, container_tag: str) -> CallerProfile | None:
        client = await self._get_client()
        try:
            # client.profile IS a callable, not a sub-resource. The SDK has
            # no `client.profile.get(...)` - that was the previous bug.
            response = await client.profile(container_tag=container_tag)
        except Exception:
            log.exception("supermemory_get_profile_failed", container_tag=container_tag)
            return None
        if response is None:
            return None
        summary = (
            getattr(response, "summary", None)
            or (response.get("summary") if isinstance(response, dict) else None)
            or ""
        )
        facts_raw = (
            getattr(response, "facts", None)
            or (response.get("facts") if isinstance(response, dict) else None)
            or {}
        )
        facts = dict(facts_raw) if isinstance(facts_raw, dict) else {}
        return CallerProfile(container_tag=container_tag, summary=_coerce_str(summary), facts=facts)

    async def delete(self, *, container_tag: str, memory_id: str) -> None:
        client = await self._get_client()
        try:
            # The SDK exposes "forget" not "delete". container_tag is REQUIRED -
            # Supermemory wants to know who is forgetting which memory.
            await client.memories.forget(container_tag=container_tag, id=memory_id)
        except Exception:
            log.exception(
                "supermemory_forget_failed",
                memory_id=memory_id,
                container_tag=container_tag,
            )
            raise
