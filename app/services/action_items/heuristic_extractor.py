"""Heuristic action-item extractor (Phase 1 F2/F3).

Pure regex matching over (a) summary blockers and (b) transcript turns.
No LLM. Each match emits an `ActionItemCandidate` that
`save_action_items()` materializes into ActionItem rows with
`status="pending_approval"`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

EXTRACTOR_NAME = "heuristic_action_item_extractor@0.1.0"

# Per LLD F3 examples + reasonable expansion.
_RX_AGENT_COMMIT = re.compile(
    r"(?:i'?ll|i will|we'?ll|we will)\s+(send|email|schedule|set up|book|follow up)",
    re.IGNORECASE,
)
_RX_LETS_DO = re.compile(
    r"(?:let'?s|let me)\s+(schedule|book|set up|send)",
    re.IGNORECASE,
)
_RX_FOLLOWUP_WHEN = re.compile(
    r"follow[- ]?up.*\b(?:by|before|on)\s+"
    r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|next week|next month|tomorrow|eod|cob)",
    re.IGNORECASE,
)

_RX_SCHEDULE_HINT = re.compile(r"\b(schedule|book|meeting|calendar|invite)\b", re.IGNORECASE)
_RX_EMAIL_HINT = re.compile(r"\b(send|email|reply|forward)\b", re.IGNORECASE)


HandlerName = Literal["scheduler", "email_drafter", "none"]


class ActionItemCandidate(BaseModel):
    """A heuristic match awaiting persistence as a pending_approval row."""

    title: str
    description: str | None = None
    handler: HandlerName = "none"
    confidence: float = 0.5
    payload: dict[str, Any] = Field(default_factory=dict)
    source_turn_idx: int | None = None  # transcript fragment index, if any
    source_blocker_idx: int | None = None
    extracted_by: str = EXTRACTOR_NAME


def _handler_hint(text: str) -> HandlerName:
    """Pick a handler based on verb hints in the matched text."""
    if _RX_SCHEDULE_HINT.search(text):
        return "scheduler"
    if _RX_EMAIL_HINT.search(text):
        return "email_drafter"
    return "none"


def _title_from(text: str, limit: int = 140) -> str:
    cleaned = " ".join(text.strip().split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


@dataclass(frozen=True)
class TranscriptTurnView:
    """Minimal shape `extract_action_item_candidates` needs from a transcript."""

    speaker: str
    text: str


def extract_action_item_candidates(
    *,
    blockers: list[str],
    transcript_turns: list[TranscriptTurnView],
) -> list[ActionItemCandidate]:
    """Run heuristics and return deduped candidates.

    Blocker -> handler="none", confidence=0.6 (Manager triages).
    Transcript turn -> handler inferred, confidence=0.7.
    Dedupe by lowercased first 60 chars of title.
    """
    out: list[ActionItemCandidate] = []

    for idx, blocker in enumerate(blockers or []):
        if not blocker or not blocker.strip():
            continue
        out.append(
            ActionItemCandidate(
                title=_title_from(blocker),
                description=blocker,
                handler="none",
                confidence=0.6,
                source_blocker_idx=idx,
                payload={"origin": "summary_blocker"},
            )
        )

    for idx, turn in enumerate(transcript_turns or []):
        text = turn.text or ""
        if not text.strip():
            continue
        matched = False
        for rx in (_RX_AGENT_COMMIT, _RX_LETS_DO, _RX_FOLLOWUP_WHEN):
            if rx.search(text):
                matched = True
                break
        if not matched:
            continue
        out.append(
            ActionItemCandidate(
                title=_title_from(text),
                description=text,
                handler=_handler_hint(text),
                confidence=0.7,
                source_turn_idx=idx,
                payload={
                    "origin": "transcript_turn",
                    "speaker": turn.speaker,
                },
            )
        )

    return _dedupe(out)


def _dedupe(items: list[ActionItemCandidate]) -> list[ActionItemCandidate]:
    seen: set[str] = set()
    deduped: list[ActionItemCandidate] = []
    for it in items:
        key = it.title[:60].lower().strip()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    return deduped


class HeuristicActionItemExtractor:
    """Class-shaped facade for callers that prefer DI."""

    name = EXTRACTOR_NAME

    def run(
        self,
        *,
        blockers: list[str],
        transcript_turns: list[TranscriptTurnView],
    ) -> list[ActionItemCandidate]:
        return extract_action_item_candidates(
            blockers=blockers, transcript_turns=transcript_turns
        )


__all__ = [
    "ActionItemCandidate",
    "EXTRACTOR_NAME",
    "HandlerName",
    "HeuristicActionItemExtractor",
    "TranscriptTurnView",
    "extract_action_item_candidates",
]
