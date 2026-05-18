"""caller_memory_writer - push a per-call digest to Supermemory.

Uses Supermemory's containerTags pattern (see app/memory/base.py). Each
write is tagged with BOTH:

  - caller_{field_employee_id}   - primary per-Rep isolation
  - workspace_{workspace_id}     - workspace boundary (analytics + delete-all)

Per LLD §C11 the digest is a compact "what was discussed / who came up"
block - NOT the full transcript verbatim. Object storage holds the archive
(via CallArtifact); Supermemory is for per-Rep gist + retrieval at the
start of the NEXT call.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db.models import Call, FieldEmployee, TranscriptFragment
from app.logging import get_logger
from app.memory.base import CallerMemoryProvider, container_tags_for
from app.miniagents.summarizer_agent import SummarizerOutput

log = get_logger(__name__)


@dataclass(frozen=True)
class CallerMemoryWriteResult:
    written: bool
    memory_id: str | None = None
    reason: str | None = None


def render_caller_memory_digest(
    *,
    call: Call,
    transcript: list[TranscriptFragment],
    summary: SummarizerOutput,
) -> str:
    """Compose the digest text. Short - this is per-Rep gist not archive."""
    lines = [
        f"Call on {call.started_at.date().isoformat()}.",
        "",
        "Discussion:",
        summary.discussion[:500],
    ]
    if summary.blockers:
        lines.append("")
        lines.append("Blockers raised by the Rep:")
        for b in summary.blockers[:5]:
            lines.append(f"- {b}")
    entity_names = [
        str(e.get("name", "")).strip()
        for e in summary.extracted_entities
        if isinstance(e, dict) and e.get("name")
    ]
    if entity_names:
        lines.append("")
        lines.append("Mentioned: " + ", ".join(entity_names[:10]))
    rep_turns = sum(1 for t in transcript if t.speaker == "caller")
    agent_turns = sum(1 for t in transcript if t.speaker == "agent")
    lines.append("")
    lines.append(f"({rep_turns} Rep turns, {agent_turns} agent turns.)")
    return "\n".join(lines)


async def write_call_to_caller_memory(
    *,
    call: Call,
    field_employee: FieldEmployee | None,
    transcript: list[TranscriptFragment],
    summary: SummarizerOutput,
    memory: CallerMemoryProvider,
) -> CallerMemoryWriteResult:
    if field_employee is None:
        return CallerMemoryWriteResult(written=False, reason="no_field_employee")

    tags = container_tags_for(call.workspace_id, field_employee.id)
    digest = render_caller_memory_digest(call=call, transcript=transcript, summary=summary)

    try:
        memory_id = await memory.add(
            container_tags=tags,
            content=digest,
            metadata={
                "call_id": str(call.id),
                "tags": ["call_digest"],
                "started_at": call.started_at.isoformat(),
                "workspace_id": str(call.workspace_id),
                "field_employee_id": str(field_employee.id),
            },
        )
    except Exception as e:
        log.exception(
            "caller_memory_write_failed",
            container_tags=tags,
            call_id=str(call.id),
        )
        return CallerMemoryWriteResult(written=False, reason=f"{type(e).__name__}: {e}")

    return CallerMemoryWriteResult(written=True, memory_id=memory_id)
