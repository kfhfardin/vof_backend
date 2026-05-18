"""FastAPI lifespan: warm up registries, open pools, ping deps."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.logging import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("lifespan_startup_begin")
    # Eager extractor registration (registry guard makes re-imports safe)
    from app.services import intake_extractors as _intake_extractors  # noqa: F401

    # Skills loader walks skills/<name>/ and registers each LLMSkill.
    from app.skills import load_all_skills

    registered = load_all_skills()
    log.info("skills_loaded", skills=registered)

    # Orchestrator swaps in the production voice + SMS handlers.
    from app.orchestrator import register_sms_with_dispatcher, register_with_dispatcher

    register_with_dispatcher()
    log.info("orchestrator_voice_handler_registered")
    register_sms_with_dispatcher()
    log.info("orchestrator_sms_handler_registered")

    # Warm the Bedrock streaming client + TLS connection so the first real
    # voice turn doesn't pay a ~12s cold-start. Best-effort: a warm-up
    # failure doesn't block startup (the first call will just be slow).
    try:
        from app.skills import get_llm_client
        from app.skills.llm_client import BedrockMessagesClient
        from app.settings import get_settings

        if get_settings().llm_provider == "bedrock":
            client = get_llm_client()
            if isinstance(client, BedrockMessagesClient):
                # Lazy-init the aiobotocore client; also kick a tiny invoke to
                # establish the TLS session + sign the first request out-of-band
                # of the hot path.
                async for _ in client.stream_chat(
                    model=get_settings().llm_default_model,
                    messages=[{"role": "user", "content": "ok"}],
                    max_tokens=1,
                ):
                    break
                log.info("bedrock_client_warmed")
    except Exception:
        log.warning("bedrock_warmup_failed", exc_info=True)

    # Warm the rest of the retrieval pipeline so the first real call doesn't
    # pay cold connection setup on Postgres, Supermemory, or the brain index.
    # Each step is best-effort; failures are logged but don't block startup.
    await _warm_retrieval_pipeline()

    log.info("lifespan_startup_complete")
    try:
        yield
    finally:
        log.info("lifespan_shutdown_begin")
        await _close_singletons()
        log.info("lifespan_shutdown_complete")


async def _warm_retrieval_pipeline() -> None:
    """Issue tiny queries against every retrieval-path dependency so the
    first real call doesn't pay cold connection / index setup costs.

    The orchestrator's per-turn retrieval racing against a 150ms deadline
    is only useful if Postgres pools, the Supermemory httpx client, and
    the pgvector index are all warm. Cold initialization here moves seconds
    out of the call path.
    """
    import asyncio

    from sqlalchemy import text

    # App + brain DB pools — establish at least one connection each.
    try:
        from app.db.app_session import app_session

        async with app_session() as session:
            await session.execute(text("SELECT 1"))
        log.info("app_db_pool_warmed")
    except Exception:
        log.warning("app_db_warmup_failed", exc_info=True)

    # Brain DB is schema-per-workspace (brain_session(workspace_id) signature),
    # so we skip a generic SELECT 1 here — the hybrid_search warmup below
    # opens a connection against the brain DB anyway.

    # Supermemory + brain hybrid search: kick a no-result query so the
    # client opens its TLS pool and the pgvector index is in page cache.
    # Both run in parallel — they're independent.
    async def _warm_supermemory() -> None:
        try:
            from app.deps import get_memory_provider
            from app.memory.stub import StubCallerMemoryProvider

            provider = get_memory_provider()
            if isinstance(provider, StubCallerMemoryProvider):
                return  # nothing to warm
            await provider.search(container_tags=["warmup_noop"], query="warmup", k=1)
            log.info("supermemory_client_warmed")
        except Exception:
            log.warning("supermemory_warmup_failed", exc_info=True)

    async def _warm_brain_index() -> None:
        try:
            from uuid import UUID

            from app.deps import get_brain_provider

            brain = get_brain_provider()
            # A nonexistent workspace_id is fine — we just want the pgvector
            # operator to be in cache. Empty result set is the expected outcome.
            await brain.hybrid_search(UUID(int=0), query="warmup", k=1)
            log.info("brain_index_warmed")
        except Exception:
            log.warning("brain_warmup_failed", exc_info=True)

    await asyncio.gather(_warm_supermemory(), _warm_brain_index())


async def _close_singletons() -> None:
    """Drain pooled connections held by long-lived singletons.

    Each adapter holds a cached client (httpx pool, aiobotocore S3 client,
    Supermemory SDK) for the process lifetime — closing them here ensures
    the connection pools drain gracefully on uvicorn shutdown instead of
    leaving sockets to the OS.

    Each close is best-effort: a failure to drain one client never blocks
    the others, and any exception is logged at warning level.
    """
    # LLM client (OpenAICompatClient or BedrockMessagesClient)
    try:
        from app.skills.llm_client import _client as _llm_singleton

        if _llm_singleton is not None and hasattr(_llm_singleton, "close"):
            await _llm_singleton.close()
            log.info("llm_client_closed")
    except Exception:
        log.warning("llm_client_close_failed", exc_info=True)

    # Telephony adapter (AgentPhoneAdapter)
    try:
        from app.deps import _telephony as _tel_singleton

        if _tel_singleton is not None and hasattr(_tel_singleton, "close"):
            await _tel_singleton.close()
            log.info("telephony_client_closed")
    except Exception:
        log.warning("telephony_client_close_failed", exc_info=True)

    # Caller-memory provider (Supermemory)
    try:
        from app.deps import _memory as _mem_singleton

        if _mem_singleton is not None and hasattr(_mem_singleton, "close"):
            await _mem_singleton.close()
            log.info("memory_client_closed")
    except Exception:
        log.warning("memory_client_close_failed", exc_info=True)

    # Object store (S3ObjectStore)
    try:
        from app.deps import _object_store as _store_singleton

        if _store_singleton is not None and hasattr(_store_singleton, "close"):
            await _store_singleton.close()
            log.info("object_store_closed")
    except Exception:
        log.warning("object_store_close_failed", exc_info=True)

    # Redis singletons (one per event loop the process used)
    try:
        from app.realtime.redis_client import reset_redis_client

        await reset_redis_client()
        log.info("redis_client_closed")
    except Exception:
        log.warning("redis_client_close_failed", exc_info=True)
