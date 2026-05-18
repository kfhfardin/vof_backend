"""Parallel context retrieval for the Orchestrator turn loop.

Issues CallerMemory.search and Brain.hybrid_search concurrently and merges
into a single RetrievedContext. The first-turn variant (prewarm_starter)
also pulls the caller profile up front so the prompt has ambient context
from turn 1.

Phase 0: hybrid_search returns []. The retrieval pattern is real - the
real Supermemory adapter (already shipped) populates caller_hits at every
turn once SUPERMEMORY_API_KEY is set; brain hits light up with §D3.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import UUID

from app.brain.base import BrainProvider, BrainSearchHit
from app.memory.base import (
    CallerMemoryHit,
    CallerMemoryProvider,
    CallerProfile,
    caller_tag,
)


@dataclass(frozen=True)
class RetrievedContext:
    caller_hits: list[CallerMemoryHit] = field(default_factory=list)
    brain_hits: list[BrainSearchHit] = field(default_factory=list)
    caller_profile: CallerProfile | None = None


class Retriever:
    def __init__(
        self,
        memory: CallerMemoryProvider,
        brain: BrainProvider,
    ) -> None:
        self.memory = memory
        self.brain = brain

    async def for_turn(
        self,
        *,
        workspace_id: UUID,
        field_employee_id: UUID | None,
        query: str,
        k_caller: int = 5,
        k_brain: int = 8,
    ) -> RetrievedContext:
        """Per-turn retrieval.

        Filters Supermemory search to the **caller tag only** to isolate the
        rep's own history. Supermemory's `container_tags` is OR-matching, not
        AND-matching (verified against the live API): passing
        [caller_X, workspace_W] would return every memory that has *either*
        tag, leaking cross-rep memories via the shared workspace tag. Writes
        still carry both tags so workspace-scoped cross-rep queries are
        possible (Manager-side surfaces, post-call analytics) via a separate
        single-tag search on the workspace tag.
        """
        if field_employee_id is not None:
            caller_task = self.memory.search(
                container_tags=[caller_tag(field_employee_id)],
                query=query,
                k=k_caller,
            )
        else:
            caller_task = asyncio.sleep(0, result=[])
        brain_task = self.brain.hybrid_search(workspace_id, query, k=k_brain)
        caller_hits, brain_hits = await asyncio.gather(caller_task, brain_task)
        return RetrievedContext(
            caller_hits=list(caller_hits or []),
            brain_hits=list(brain_hits or []),
        )

    async def prewarm_starter(
        self,
        *,
        workspace_id: UUID,
        field_employee_id: UUID | None,
    ) -> RetrievedContext:
        """Called once per call before the first turn.

        Pulls the caller profile (Supermemory's aggregate) and a broad brain
        snapshot. Uses the per-caller tag for the profile fetch.
        """
        if field_employee_id is not None:
            profile_task = self.memory.get_profile(caller_tag(field_employee_id))
        else:
            profile_task = asyncio.sleep(0, result=None)
        brain_task = self.brain.hybrid_search(workspace_id, query="*", k=20)
        profile, brain_hits = await asyncio.gather(profile_task, brain_task)
        return RetrievedContext(
            caller_hits=[],
            brain_hits=list(brain_hits or []),
            caller_profile=profile,
        )
