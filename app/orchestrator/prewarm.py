"""Per-call context prewarm — cuts cold-retrieval latency on turn 1.

AP doesn't fire a separate `call.started` event, so the earliest moment we
know a call exists is the first `agent.message:voice` webhook. At that
point we kick off `prewarm_call_context()` as a background task: it pulls
the caller's Supermemory profile + a broad workspace-brain snapshot and
stashes them in Redis under `prewarm:call:{call_id}`.

The TurnLoop on subsequent turns loads this stash and uses it as the
fallback context when fresh retrieval doesn't finish inside the speculative
race window. Stash survives 30min — long enough for any call, short enough
to free abandoned-call state.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Any
from uuid import UUID

from app.brain.base import BrainProvider, BrainSearchHit
from app.logging import get_logger
from app.memory.base import CallerMemoryHit, CallerMemoryProvider, CallerProfile
from app.orchestrator.retrieval import RetrievedContext, Retriever
from app.realtime.redis_client import get_redis

log = get_logger(__name__)

PREWARM_KEY_PREFIX = "prewarm:call:"
PREWARM_TTL_SECONDS = 30 * 60  # 30 min - longer than any realistic call


def _key(call_id: UUID) -> str:
    return f"{PREWARM_KEY_PREFIX}{call_id}"


def _serialize(ctx: RetrievedContext) -> str:
    return json.dumps(
        {
            "caller_hits": [_serialize_caller_hit(h) for h in ctx.caller_hits],
            "brain_hits": [_serialize_brain_hit(h) for h in ctx.brain_hits],
            "caller_profile": _serialize_profile(ctx.caller_profile),
        }
    )


def _serialize_caller_hit(h: CallerMemoryHit) -> dict[str, Any]:
    return {"id": h.id, "content": h.content, "score": h.score, "metadata": h.metadata}


def _serialize_brain_hit(h: BrainSearchHit) -> dict[str, Any]:
    return {"slug": h.slug, "title": h.title, "snippet": h.snippet, "score": h.score}


def _serialize_profile(p: CallerProfile | None) -> dict[str, Any] | None:
    if p is None:
        return None
    # CallerProfile is a small dataclass; asdict handles it
    return asdict(p)


def _deserialize(raw: str) -> RetrievedContext:
    data = json.loads(raw)
    caller_hits = [
        CallerMemoryHit(id=h["id"], content=h["content"], score=h["score"], metadata=h.get("metadata", {}))
        for h in data.get("caller_hits", [])
    ]
    brain_hits = [
        BrainSearchHit(slug=h["slug"], title=h["title"], snippet=h["snippet"], score=h["score"])
        for h in data.get("brain_hits", [])
    ]
    profile_dict = data.get("caller_profile")
    profile = CallerProfile(**profile_dict) if profile_dict else None
    return RetrievedContext(caller_hits=caller_hits, brain_hits=brain_hits, caller_profile=profile)


async def stash_prewarm_context(call_id: UUID, ctx: RetrievedContext) -> None:
    r = get_redis()
    await r.set(_key(call_id), _serialize(ctx), ex=PREWARM_TTL_SECONDS)


async def load_prewarm_context(call_id: UUID) -> RetrievedContext | None:
    """Cheap (~1ms) Redis read used by every turn before fresh retrieval races."""
    r = get_redis()
    raw = await r.get(_key(call_id))
    if raw is None:
        return None
    try:
        return _deserialize(raw.decode("utf-8"))
    except Exception:
        log.warning("prewarm_deserialize_failed", call_id=str(call_id), exc_info=True)
        return None


async def clear_prewarm_context(call_id: UUID) -> None:
    """Called from CallEnded handler — no point hanging onto state for a dead call."""
    r = get_redis()
    await r.delete(_key(call_id))


async def prewarm_call_context(
    *,
    call_id: UUID,
    workspace_id: UUID,
    field_employee_id: UUID | None,
    memory: CallerMemoryProvider,
    brain: BrainProvider,
) -> None:
    """Fire-and-forget task body. Schedule via asyncio.create_task(...).

    Errors are swallowed (logged) — a prewarm failure must never block the
    real per-turn retrieval, which will fall back to a fresh search.
    """
    try:
        retriever = Retriever(memory=memory, brain=brain)
        ctx = await retriever.prewarm_starter(
            workspace_id=workspace_id,
            field_employee_id=field_employee_id,
        )
        await stash_prewarm_context(call_id, ctx)
        log.info(
            "prewarm_stashed",
            call_id=str(call_id),
            n_brain_hits=len(ctx.brain_hits),
            has_profile=ctx.caller_profile is not None,
        )
    except Exception:
        log.warning("prewarm_failed", call_id=str(call_id), exc_info=True)


def schedule_prewarm(
    *,
    call_id: UUID,
    workspace_id: UUID,
    field_employee_id: UUID | None,
    memory: CallerMemoryProvider,
    brain: BrainProvider,
) -> asyncio.Task[None]:
    """Synchronously schedule the prewarm coroutine and return the task.

    Use from the webhook handler after Call materialization. Caller does
    NOT await — the prewarm runs concurrently with the live turn-1 work.
    """
    return asyncio.create_task(
        prewarm_call_context(
            call_id=call_id,
            workspace_id=workspace_id,
            field_employee_id=field_employee_id,
            memory=memory,
            brain=brain,
        )
    )
