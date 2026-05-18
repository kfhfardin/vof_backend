"""Per-turn driver.

Steps (per HLD §15 timeline):

  1. Load session (or create on first turn).
  2. Persist the caller's transcript fragment.
  3. Parallel retrieval (CallerMemory + Brain hybrid).
  4. Emit bridge chunk if retrieval > 300ms.
  5. Render the orchestrator prompt.
  6. Stream LLM tokens, wrap into NDJSON, yield each chunk.
  7. Persist the agent's reply as a transcript fragment.
  8. Append both turns to session.conversation_history; save.

The loop is the integration point - retrieval, prompt rendering, streaming,
and persistence each live in their own module above.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.brain.base import BrainProvider
from app.db.app_session import app_session
from app.db.repositories.calls_repo import CallsRepo
from app.db.repositories.decisions_repo import DecisionsRepo
from app.db.repositories.field_employees_repo import FieldEmployeesRepo
from app.db.repositories.transcripts_repo import TranscriptsRepo
from app.db.repositories.workspaces_repo import WorkspacesRepo
from app.errors import NotFound
from app.logging import get_logger
from app.memory.base import CallerMemoryProvider
from app.orchestrator.prompts import decision_updates_from_rows, render_messages
from app.orchestrator.retrieval import Retriever
from app.orchestrator.session import RedisSessionStore
from app.orchestrator.streaming import (
    hangup_chunk,
    token_stream_to_ndjson,
)
from app.orchestrator.tool_dispatch import scan_for_tool_calls
from app.orchestrator.tools import ToolContext, ToolRegistry
from app.realtime.bus import publish_frame
from app.schemas.ws_frames import TranscriptFragmentFrame
from app.settings import get_settings
from app.skills import LLMClient, get_llm_client
from app.telephony.events import InboundVoiceTurn

log = get_logger(__name__)


class TurnLoop:
    """Wires session + retrieval + prompts + streaming into one call.

    A single instance is created per voice-turn webhook; lightweight to
    construct so no caching is needed.
    """

    def __init__(
        self,
        *,
        memory: CallerMemoryProvider,
        brain: BrainProvider,
        llm: LLMClient | None = None,
    ) -> None:
        self._memory = memory
        self._brain = brain
        self._llm = llm or get_llm_client()
        self._session_store = RedisSessionStore()
        self._retriever = Retriever(memory, brain)

    async def run(
        self,
        event: InboundVoiceTurn,
        *,
        call_id: UUID,
    ) -> AsyncIterator[bytes]:
        # Step 1-2: load the workspace + call + session, persist caller turn.
        async with app_session() as session:
            calls = CallsRepo(session)
            workspaces = WorkspacesRepo(session)
            transcripts = TranscriptsRepo(session)
            field_employees = FieldEmployeesRepo(session)

            call = await calls.get(call_id)
            if call is None:
                raise NotFound(f"call {call_id} not found")
            workspace = await workspaces.get_by_id(call.workspace_id)
            if workspace is None:
                raise NotFound(f"workspace {call.workspace_id} not found")
            field_employee = (
                await field_employees.get(call.field_employee_id) if call.field_employee_id else None
            )

            now = event.delivery_timestamp or datetime.now(UTC)
            caller_fragment = await transcripts.append(
                call_id=call_id,
                workspace_id=workspace.id,
                speaker="caller",
                text=event.transcript,
                ts=now,
            )
            await session.commit()

            # Materialize a primitive snapshot - we'll commit the agent fragment
            # in a fresh session after streaming completes.
            workspace_id = workspace.id
            field_employee_snapshot = field_employee
            workspace_snapshot = workspace
            caller_seq = caller_fragment.seq

        # Publish the caller frame to the multi-call WS bus.
        await publish_frame(
            workspace_id,
            TranscriptFragmentFrame(
                call_id=call_id,
                speaker="caller",
                text=event.transcript,
                seq=caller_seq,
                ts=now,
            ).model_dump(mode="json"),
        )

        # Step 3-4: speculative retrieval race.
        #
        # Goal: don't block the LLM start on cold retrieval. Three sources of
        # context, in order of preference:
        #   (a) prewarmed snapshot in Redis (from app.orchestrator.prewarm —
        #       fires on Call creation, Supermemory profile + broad brain hits)
        #   (b) fresh per-turn retrieval (Caller Memory query + Brain hybrid)
        #   (c) empty fallback if both miss
        #
        # We start (b) immediately as a background task and race it against a
        # short deadline. If (b) lands inside the deadline we use the fresh
        # context. Otherwise we emit the bridge chunk, fall back to (a), and
        # the background (b) keeps running — its eventual result is stashed
        # for the NEXT turn via the same prewarm cache, so multi-turn calls
        # converge to fresh context within one turn of lag.
        from app.orchestrator.prewarm import (
            load_prewarm_context,
            stash_prewarm_context,
        )

        sess = await self._session_store.load_or_create(
            call_id=call_id,
            workspace_id=workspace_id,
            field_employee_id=field_employee_snapshot.id if field_employee_snapshot else None,
        )
        sess.append_turn(speaker="caller", text=event.transcript, ts=now)

        import asyncio as _asyncio

        from app.orchestrator.retrieval import RetrievedContext

        prewarmed_task = _asyncio.create_task(load_prewarm_context(call_id))
        retrieval_task = _asyncio.create_task(
            self._retriever.for_turn(
                workspace_id=workspace_id,
                field_employee_id=field_employee_snapshot.id if field_employee_snapshot else None,
                query=event.transcript,
            )
        )

        # Race fresh retrieval against a short deadline. Shield so the task
        # keeps running after a timeout — we want its result for next turn.
        SPECULATIVE_DEADLINE_MS = 150
        context: RetrievedContext
        try:
            context = await _asyncio.wait_for(
                _asyncio.shield(retrieval_task),
                timeout=SPECULATIVE_DEADLINE_MS / 1000.0,
            )
            log.info(
                "retrieval_won_race",
                call_id=str(call_id),
                deadline_ms=SPECULATIVE_DEADLINE_MS,
            )
        except TimeoutError:
            # Fresh retrieval too slow. Fall back to prewarmed snapshot.
            prewarmed = await prewarmed_task
            context = prewarmed if prewarmed is not None else RetrievedContext()
            log.info(
                "retrieval_speculative_fallback",
                call_id=str(call_id),
                used_prewarm=prewarmed is not None,
            )
            # Emit bridge chunk so the caller hears something while we proceed.
            from app.orchestrator.streaming import _ndjson as _ndjson_chunk
            import random

            yield _ndjson_chunk(
                {
                    "text": random.choice(
                        [
                            "Let me check on that...",
                            "Give me a sec...",
                            "One moment...",
                            "Hold on, looking that up...",
                        ]
                    ),
                    "interim": True,
                }
            )

        # Whether we used fresh or prewarmed context, the fresh retrieval
        # eventually completes — stash its result for the NEXT turn so this
        # call gradually warms its own cache.
        def _stash_on_completion(t: _asyncio.Task[RetrievedContext]) -> None:
            if t.cancelled() or t.exception() is not None:
                return
            _asyncio.create_task(stash_prewarm_context(call_id, t.result()))

        if retrieval_task.done():
            _stash_on_completion(retrieval_task)
        else:
            retrieval_task.add_done_callback(_stash_on_completion)

        # Step 4b: pull any pending decisions that resolved since last turn
        # so the prompt can weave the answer (or the timeout notice) in.
        # Pruning: any answered/timed_out decision is removed from
        # session.pending_decisions after we render - one update per resolution.
        decision_updates = []
        still_pending: list[str] = []
        if sess.pending_decisions:
            async with app_session() as ds:
                drepo = DecisionsRepo(ds)
                from uuid import UUID

                rows = []
                for did in sess.pending_decisions:
                    try:
                        d = await drepo.get(UUID(did))
                    except (ValueError, TypeError):
                        continue
                    if d is None:
                        continue
                    if d.status in ("answered", "timed_out"):
                        rows.append(d)
                    else:
                        still_pending.append(did)
                decision_updates = decision_updates_from_rows(rows)
            sess.pending_decisions = still_pending

        # Step 4c: drain pending Manager whispers (F7) so the next prompt sees
        # them. Best-effort; Redis hiccup falls through to no whispers.
        try:
            from app.realtime.redis_client import get_redis as _get_redis

            r = _get_redis()
            wkey = f"whispers:{call_id}"
            raw_whispers = await r.lrange(wkey, 0, -1)
            if raw_whispers:
                await r.delete(wkey)
                import json as _json

                for raw in raw_whispers:
                    try:
                        entry = _json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                    except (ValueError, TypeError):
                        continue
                    g = entry.get("guidance")
                    iid = entry.get("intervention_id")
                    if g:
                        sess.manager_whispers.append(g)
                    if iid:
                        sess.pending_intervention_ids.append(iid)
        except Exception as _e:
            log.warning("whisper_drain_failed", call_id=str(call_id), error=str(_e))

        # Step 5: render the orchestrator prompt.
        messages = render_messages(
            workspace=workspace_snapshot,
            field_employee=field_employee_snapshot,
            session=sess,
            context=context,
            rep_utterance=event.transcript,
            decision_updates=decision_updates,
        )

        # Step 6: stream the LLM reply through the tool-marker scanner.
        # Text events are wrapped into NDJSON; tool_call events are dispatched
        # via ToolRegistry. After a tool runs, ToolResult.bridge_text becomes
        # the final spoken NDJSON chunk and ToolResult.end_turn closes the
        # stream. hangup chunks are emitted for end_call.
        model = get_settings().llm_default_model
        token_iter = self._llm.stream_chat(model=model, messages=messages)
        spoken_parts: list[str] = []
        tool_results: list[dict[str, Any]] = []
        hangup_pending = False

        async def _text_substream() -> AsyncIterator[str]:
            """Yield text events from the marker scanner; dispatch tool calls
            inline. `return` closes the substream when a tool sets end_turn,
            which naturally closes the NDJSON wrapper."""
            nonlocal hangup_pending
            async for kind, payload in scan_for_tool_calls(token_iter):
                if kind == "text":
                    spoken_parts.append(payload)
                    yield payload
                elif kind == "tool_call":
                    ctx = ToolContext(
                        workspace_id=workspace_id,
                        call_id=call_id,
                        field_employee_id=(field_employee_snapshot.id if field_employee_snapshot else None),
                    )
                    try:
                        result = await ToolRegistry.dispatch(ctx, payload["name"], payload["args"])
                    except Exception as e:
                        log.exception(
                            "tool_dispatch_failed",
                            tool=payload.get("name"),
                            call_id=str(call_id),
                        )
                        bridge = f"Hmm, I hit a snag - {type(e).__name__}. Moving on for now."
                        spoken_parts.append(bridge)
                        yield bridge
                        return
                    tool_results.append(
                        {
                            "name": payload["name"],
                            "followup_context": result.followup_context,
                        }
                    )
                    if result.bridge_text:
                        spoken_parts.append(result.bridge_text)
                        yield result.bridge_text
                    if result.hangup:
                        hangup_pending = True
                    if result.end_turn:
                        return
                elif kind == "error":
                    log.warning("tool_marker_error", detail=str(payload))
                elif kind == "done":
                    return

        async for chunk_bytes in token_stream_to_ndjson(_text_substream()):
            yield chunk_bytes
        if hangup_pending:
            yield hangup_chunk()

        agent_reply = "".join(spoken_parts).strip()

        # Persist any opened decision ids in session.pending_decisions so the
        # next turn's prompt picks them up (when the Manager responds and the
        # session bus delivers the resolution, this list is the join key).
        for tr in tool_results:
            fc = tr.get("followup_context") or {}
            new_decision = fc.get("decision_id")
            if new_decision and str(new_decision) not in sess.pending_decisions:
                sess.pending_decisions.append(str(new_decision))

        # Step 7-8: persist agent fragment + save session.
        if agent_reply:
            agent_ts = datetime.now(UTC)
            async with app_session() as session2:
                transcripts2 = TranscriptsRepo(session2)
                agent_fragment = await transcripts2.append(
                    call_id=call_id,
                    workspace_id=workspace_id,
                    speaker="agent",
                    text=agent_reply,
                    ts=agent_ts,
                )
                await session2.commit()
                agent_seq = agent_fragment.seq
            sess.append_turn(speaker="agent", text=agent_reply, ts=agent_ts)
            await publish_frame(
                workspace_id,
                TranscriptFragmentFrame(
                    call_id=call_id,
                    speaker="agent",
                    text=agent_reply,
                    seq=agent_seq,
                    ts=agent_ts,
                ).model_dump(mode="json"),
            )

        # Move any whispers used in this turn to consumed; stamp the rows.
        if sess.manager_whispers:
            sess.consumed_whispers.extend(sess.manager_whispers)
            sess.manager_whispers = []
            turn_number = len(sess.conversation_history)
            if sess.pending_intervention_ids:
                pending_ids = list(sess.pending_intervention_ids)
                sess.pending_intervention_ids = []
                try:
                    from app.db.repositories.manager_interventions_repo import (
                        ManagerInterventionsRepo,
                    )

                    async with app_session() as isess:
                        irepo = ManagerInterventionsRepo(isess)
                        for iid in pending_ids:
                            try:
                                await irepo.mark_consumed(UUID(iid), turn_number=turn_number)
                            except (ValueError, TypeError):
                                continue
                        await isess.commit()
                except Exception as _e:
                    log.warning("intervention_stamp_failed", call_id=str(call_id), error=str(_e))

        try:
            await self._session_store.save(sess)
        except Exception as e:
            # Session save failure is non-fatal for the caller - we have the
            # durable transcript. Log + move on.
            log.warning("session_save_failed", call_id=str(call_id), error=str(e))
