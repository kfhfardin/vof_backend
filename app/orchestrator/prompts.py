"""Render the orchestrator skill's two Jinja templates.

The Orchestrator is the one skill that streams free-form text, so it
bypasses LLMSkill.run() and renders both templates directly here, then
feeds them as the system + user messages of a chat completion.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.db.models import DecisionRequest, FieldEmployee, ManagerWorkspace
from app.orchestrator.retrieval import RetrievedContext
from app.orchestrator.session import CallSession

SKILL_DIR = Path(__file__).resolve().parents[2] / "skills" / "orchestrator"

_env = Environment(
    loader=FileSystemLoader(SKILL_DIR),
    undefined=StrictUndefined,
    autoescape=False,
)
_system_tpl = _env.get_template("system_prompt.j2")
_turn_tpl = _env.get_template("turn_prompt.j2")


@dataclass(frozen=True)
class DecisionUpdate:
    """A pending decision the last turn opened, now resolved one way or
    another - the LLM needs to know on this turn so it can weave the
    answer back into the conversation (per HLD §5.5.3).
    """

    decision_id: str
    prompt: str
    status: str  # "answered" | "timed_out"
    response: str | None  # null for timeouts
    via: str | None  # "websocket" | "sms" | "timeout"


def _caller_block(field_employee: FieldEmployee | None, profile_summary: str | None) -> dict[str, object]:
    if field_employee is None:
        return {
            "name": None,
            "role": None,
            "team": None,
            "profiled": False,
            "profile_summary": profile_summary,
            "facts": {},
        }
    return {
        "name": field_employee.name,
        "role": field_employee.role,
        "team": field_employee.team,
        "profiled": field_employee.profiled,
        "profile_summary": profile_summary,
        "facts": field_employee.profile or {},
    }


def _hits_to_blocks(context: RetrievedContext) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    caller_hits = [
        {
            "source": "caller_memory",
            "slug_or_id": hit.id,
            "title": str(hit.metadata.get("title", "")),
            "snippet": hit.content[:280],
        }
        for hit in context.caller_hits
    ]
    brain_hits = [
        {
            "source": "brain",
            "slug_or_id": hit.slug,
            "title": hit.title,
            "snippet": hit.snippet[:280],
        }
        for hit in context.brain_hits
    ]
    return caller_hits, brain_hits


def decision_updates_from_rows(rows: list[DecisionRequest]) -> list[DecisionUpdate]:
    """Convert a list of DecisionRequest rows (typically from session.pending_decisions
    re-fetched) into the prompt-friendly DecisionUpdate shape. Skips still-open
    rows since they don't need to influence the next turn yet.
    """
    out: list[DecisionUpdate] = []
    for d in rows:
        if d.status not in ("answered", "timed_out"):
            continue
        out.append(
            DecisionUpdate(
                decision_id=str(d.id),
                prompt=d.prompt,
                status=d.status,
                response=d.response,
                via=d.responded_via,
            )
        )
    return out


def render_messages(
    *,
    workspace: ManagerWorkspace,
    field_employee: FieldEmployee | None,
    session: CallSession,
    context: RetrievedContext,
    rep_utterance: str,
    decision_updates: list[DecisionUpdate] | None = None,
) -> list[dict[str, str]]:
    """Return OpenAI-compat chat messages for the streaming completion."""
    profile_summary = context.caller_profile.summary if context.caller_profile is not None else None
    caller = _caller_block(field_employee, profile_summary)
    caller_hits, brain_hits = _hits_to_blocks(context)

    system_msg = _system_tpl.render(
        workspace_name=workspace.name,
        caller=caller,
    )
    user_msg = _turn_tpl.render(
        workspace_name=workspace.name,
        caller=caller,
        rep_utterance=rep_utterance,
        conversation_history=[
            {"speaker": t.speaker, "text": t.text, "ts": t.ts} for t in session.conversation_history
        ],
        caller_hits=caller_hits,
        brain_hits=brain_hits,
        manager_whispers=session.manager_whispers,
        decision_updates=[
            {
                "prompt": d.prompt,
                "status": d.status,
                "response": d.response,
                "via": d.via,
            }
            for d in (decision_updates or [])
        ],
    )
    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]
