"""CallSession + Redis-backed store.

State carried across turns for a single live call. Backed by Redis at
`session:call:{call_id}` (JSON-encoded). TTL is max-call-duration + buffer
so an abandoned call eventually frees the key.

Concurrency: state_version + check-and-set on save. Each save increments
state_version and writes with a Lua-style guard (read prior, compare, write).
A second writer with stale state_version raises CASMismatch and must reload.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.errors import VotFError
from app.realtime.redis_client import get_redis

SESSION_KEY_PREFIX = "session:call:"
SESSION_TTL_SECONDS = 4 * 60 * 60 + 5 * 60  # 4h + 5m buffer per LLD §C4
HISTORY_CAP = 40  # last N turns kept in-session


class CASMismatch(VotFError):
    """Save raced - reload and retry."""

    http_status = 409
    code = "session_cas_mismatch"


@dataclass
class Turn:
    """One round-trip in the conversation."""

    speaker: str  # "caller" | "agent"
    text: str
    ts: str  # ISO timestamp


@dataclass
class CallSession:
    call_id: UUID
    workspace_id: UUID
    field_employee_id: UUID | None
    conversation_history: list[Turn] = field(default_factory=list)
    # Cached retrievals: e.g. {"starter": {...}, "turn:7": {...}}
    retrieved_cache: dict[str, Any] = field(default_factory=dict)
    # IDs of decisions opened mid-call (DecisionRequest rows; populated §C6).
    pending_decisions: list[str] = field(default_factory=list)
    # Manager whispers - populated in Phase 1 §D4; placeholder list shipped now
    # so the prompt renderer doesn't need to branch.
    manager_whispers: list[str] = field(default_factory=list)
    # Whispers that have already been folded into a turn prompt. Kept for audit.
    consumed_whispers: list[str] = field(default_factory=list)
    # IDs of pending ManagerIntervention rows that need their `consumed_at_turn`
    # stamped after the next turn completes.
    pending_intervention_ids: list[str] = field(default_factory=list)
    state_version: int = 0

    def append_turn(self, *, speaker: str, text: str, ts: datetime) -> None:
        self.conversation_history.append(Turn(speaker=speaker, text=text, ts=ts.isoformat()))
        if len(self.conversation_history) > HISTORY_CAP:
            self.conversation_history = self.conversation_history[-HISTORY_CAP:]

    def to_json(self) -> str:
        return json.dumps(
            {
                "call_id": str(self.call_id),
                "workspace_id": str(self.workspace_id),
                "field_employee_id": str(self.field_employee_id) if self.field_employee_id else None,
                "conversation_history": [asdict(t) for t in self.conversation_history],
                "retrieved_cache": self.retrieved_cache,
                "pending_decisions": self.pending_decisions,
                "manager_whispers": self.manager_whispers,
                "consumed_whispers": self.consumed_whispers,
                "pending_intervention_ids": self.pending_intervention_ids,
                "state_version": self.state_version,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> CallSession:
        data = json.loads(raw)
        return cls(
            call_id=UUID(data["call_id"]),
            workspace_id=UUID(data["workspace_id"]),
            field_employee_id=UUID(data["field_employee_id"]) if data.get("field_employee_id") else None,
            conversation_history=[Turn(**t) for t in data.get("conversation_history", [])],
            retrieved_cache=data.get("retrieved_cache", {}),
            pending_decisions=data.get("pending_decisions", []),
            manager_whispers=data.get("manager_whispers", []),
            consumed_whispers=data.get("consumed_whispers", []),
            pending_intervention_ids=data.get("pending_intervention_ids", []),
            state_version=int(data.get("state_version", 0)),
        )


class RedisSessionStore:
    @staticmethod
    def _key(call_id: UUID) -> str:
        return f"{SESSION_KEY_PREFIX}{call_id}"

    async def load(self, call_id: UUID) -> CallSession | None:
        r = get_redis()
        raw = await r.get(self._key(call_id))
        if raw is None:
            return None
        return CallSession.from_json(raw.decode("utf-8"))

    async def load_or_create(
        self,
        *,
        call_id: UUID,
        workspace_id: UUID,
        field_employee_id: UUID | None,
    ) -> CallSession:
        existing = await self.load(call_id)
        if existing is not None:
            return existing
        return CallSession(
            call_id=call_id,
            workspace_id=workspace_id,
            field_employee_id=field_employee_id,
        )

    async def save(self, session: CallSession) -> None:
        """Persist with check-and-set on state_version.

        Increments state_version atomically with the write; raises CASMismatch
        if another writer beat us.
        """
        r = get_redis()
        key = self._key(session.call_id)

        # Watch + multi/exec for CAS. redis-py exposes pipeline transactions.
        async with r.pipeline(transaction=True) as pipe:
            try:
                await pipe.watch(key)
                current_raw = await pipe.get(key)
                if current_raw is not None:
                    current = CallSession.from_json(current_raw.decode("utf-8"))
                    if current.state_version != session.state_version:
                        await pipe.unwatch()
                        raise CASMismatch(
                            f"call {session.call_id} state_version mismatch "
                            f"(have {session.state_version}, redis has {current.state_version})"
                        )
                session.state_version += 1
                pipe.multi()
                await pipe.set(key, session.to_json(), ex=SESSION_TTL_SECONDS)
                await pipe.execute()
            except CASMismatch:
                raise
            except Exception as e:
                # Watch was already consumed by execute() in the happy path; on
                # other errors, leave the key untouched.
                raise VotFError(f"session save failed: {e}") from e

    async def delete(self, call_id: UUID) -> None:
        r = get_redis()
        await r.delete(self._key(call_id))
