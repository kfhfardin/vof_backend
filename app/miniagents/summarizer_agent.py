"""Summarizer mini-agent - wraps the summarizer skill in a worker-friendly
signature. The actual prompt + schema live in skills/summarizer/.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db.models import Call, TranscriptFragment
from app.skills import SkillContext, SkillRegistry


@dataclass(frozen=True)
class SummarizerInput:
    call: Call
    caller_name: str | None
    caller_role: str | None
    transcript: list[TranscriptFragment]
    provider_summary_text: str | None
    brain_context: list[dict[str, str]]


@dataclass(frozen=True)
class SummarizerOutput:
    discussion: str
    blockers: list[str]
    extracted_entities: list[dict[str, str | None]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "discussion": self.discussion,
            "blockers": self.blockers,
            "extracted_entities": self.extracted_entities,
        }


def _build_input_dict(inputs: SummarizerInput) -> dict[str, Any]:
    return {
        "call_id": str(inputs.call.id),
        "started_at": inputs.call.started_at.isoformat(),
        "caller": {"name": inputs.caller_name, "role": inputs.caller_role},
        "transcript": [
            {"speaker": t.speaker, "text": t.text, "ts": t.ts.isoformat()} for t in inputs.transcript
        ],
        "provider_summary": inputs.provider_summary_text,
        "brain_context": inputs.brain_context,
    }


async def run_summarizer(inputs: SummarizerInput) -> SummarizerOutput:
    skill = SkillRegistry.get("summarizer")
    skill_in = skill.input_schema.model_validate(_build_input_dict(inputs))
    raw_out = await skill.run(skill_in, SkillContext(workspace_id=inputs.call.workspace_id))
    # Convert pydantic Output -> our worker-facing dataclass
    out_dict = raw_out.model_dump()
    return SummarizerOutput(
        discussion=str(out_dict.get("discussion", "")),
        blockers=list(out_dict.get("blockers", []) or []),
        extracted_entities=[
            {
                "type": str(e.get("type", "")),
                "name": str(e.get("name", "")),
                "slug_hint": e.get("slug_hint"),
            }
            for e in (out_dict.get("extracted_entities") or [])
            if isinstance(e, dict) and e.get("name")
        ],
    )


class Summarizer:
    """Class-shaped facade for callers that prefer DI."""

    name = "summarizer"

    async def run(self, inputs: SummarizerInput) -> SummarizerOutput:
        return await run_summarizer(inputs)


__all__ = [
    "Summarizer",
    "SummarizerInput",
    "SummarizerOutput",
    "run_summarizer",
]
