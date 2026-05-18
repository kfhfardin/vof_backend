"""dashboard_rollup mini-agent - the nightly per-workspace rollup (LLD §F8).

Sequence (single transaction for the snapshot rows + surfaced-stamping):

  1. Compute the aggregate (call count, missed decisions, reps in motion,
     etc.) via `compute_aggregate`.
  2. Run the `dashboard_rollup_writer` skill to render the brief sections +
     subject line. Falls back to a structured-only skeleton if the skill
     isn't registered yet (the skills agent ships it separately).
  3. Persist the brief artifact JSON to object storage. The lookup key is
     stamped into the overview DashboardSnapshot's `metrics.brief_id` for
     the GET endpoint.
  4. Write per-dimension DashboardSnapshot rows.
  5. Stamp `surfaced_in_brief_at` on the missed decisions so they appear in
     exactly one brief.
  6. If the workspace opted into email delivery, enqueue the email_delivery
     job. Best-effort - a Redis hiccup doesn't roll back the brief.

The artifact JSON layout matches `DailyBriefResponse` in
`app/schemas/dashboard.py` so the endpoint can return it directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from app.db.app_session import app_session
from app.db.repositories.workspaces_repo import WorkspacesRepo
from app.deps import get_object_store
from app.logging import get_logger
from app.services.dashboards.aggregator import (
    compute_aggregate,
    mark_decisions_surfaced,
    write_snapshots,
)
from app.skills import SkillContext, SkillRegistry
from app.storage.base import workspace_key

log = get_logger(__name__)


@dataclass(frozen=True)
class DashboardRollupInput:
    workspace_id: UUID
    brief_date: date


@dataclass(frozen=True)
class DashboardRollupResult:
    brief_artifact_id: UUID
    snapshots_written: int


def _build_skill_inputs(agg: Any) -> dict[str, Any]:
    """Render the structured payload the dashboard_rollup_writer skill expects."""
    return {
        "workspace_id": str(agg.workspace_id),
        "workspace_name": agg.workspace_name,
        "brief_date": agg.brief_date.isoformat(),
        "call_count": agg.call_count,
        "top_topics": list(agg.top_topics),
        "urgent_flags": list(agg.urgent_flags),
        "missed_decisions": [
            {
                "decision_id": m.decision_id,
                "prompt": m.prompt,
                "call_id": m.call_id,
                "caller_name": m.caller_name,
                "options": list(m.options),
                "timed_out_at_iso": m.timed_out_at_iso,
            }
            for m in agg.missed_decisions
        ],
        "account_movement": [
            {
                "slug": a.slug,
                "title": a.title,
                "new_timeline_entries": a.new_timeline_entries,
                "new_blockers": list(a.new_blockers),
            }
            for a in agg.account_movement
        ],
        "reps_in_motion": [
            {
                "field_employee_id": r.field_employee_id,
                "name": r.name,
                "call_count": r.call_count,
                "top_topics": list(r.top_topics),
            }
            for r in agg.reps_in_motion
        ],
        "stub_escalations": [
            {"slug": s.slug, "title": s.title, "mention_count": s.mention_count}
            for s in agg.stub_escalations
        ],
    }


def _fallback_render(agg: Any) -> tuple[str, dict[str, Any]]:
    """Used when the dashboard_rollup_writer skill is not registered yet.

    Produces a skeleton that mirrors the section structure so the FE can
    render something useful even before the skills agent lands.
    """
    subject = f"{agg.workspace_name} daily brief - {agg.brief_date.isoformat()}"
    sections = {
        "yesterday_at_a_glance": {
            "call_count": agg.call_count,
            "top_topics": list(agg.top_topics),
            "urgent_flags": list(agg.urgent_flags),
        },
        "decisions_you_missed": [
            {
                "decision_id": m.decision_id,
                "prompt": m.prompt,
                "options": list(m.options),
                "caller_name": m.caller_name,
                "timed_out_at": m.timed_out_at_iso,
            }
            for m in agg.missed_decisions
        ],
        "account_movement": [
            {"slug": a.slug, "title": a.title, "new_timeline_entries": a.new_timeline_entries}
            for a in agg.account_movement
        ],
        "reps_in_motion": [
            {"name": r.name, "call_count": r.call_count} for r in agg.reps_in_motion
        ],
        "stub_to_real_escalations": [
            {"slug": s.slug, "title": s.title} for s in agg.stub_escalations
        ],
    }
    return subject, sections


async def _render_brief(agg: Any, workspace_id: UUID) -> tuple[str, dict[str, Any]]:
    try:
        skill = SkillRegistry.get("dashboard_rollup_writer")
    except KeyError:
        log.info("dashboard_rollup_writer_skill_missing_using_fallback")
        return _fallback_render(agg)

    try:
        skill_input = skill.input_schema.model_validate(_build_skill_inputs(agg))
        rendered = await skill.run(skill_input, SkillContext(workspace_id=workspace_id))
        # Skill output: pydantic model with .subject_line + .sections
        subject_line = getattr(rendered, "subject_line", None) or ""
        sections_attr = getattr(rendered, "sections", None)
        if sections_attr is None:
            sections = rendered.model_dump()
        elif hasattr(sections_attr, "model_dump"):
            sections = sections_attr.model_dump()
        else:
            sections = dict(sections_attr)
        return subject_line, sections
    except Exception:
        log.exception("dashboard_rollup_writer_skill_failed_using_fallback")
        return _fallback_render(agg)


async def run_dashboard_rollup(inputs: DashboardRollupInput) -> DashboardRollupResult:
    storage = get_object_store()
    brief_id = uuid4()
    snapshots_written = 0
    manager_email: str | None = None
    email_opted_in = False

    async with app_session() as session:
        ws_repo = WorkspacesRepo(session)
        workspace = await ws_repo.get_by_id(inputs.workspace_id)
        if workspace is None:
            raise ValueError(f"workspace not found: {inputs.workspace_id}")

        agg = await compute_aggregate(session, inputs.workspace_id, inputs.brief_date)
        subject, sections = await _render_brief(agg, inputs.workspace_id)

        now = datetime.now(timezone.utc)
        artifact_payload = {
            "brief_id": str(brief_id),
            "workspace_id": str(inputs.workspace_id),
            "brief_date": inputs.brief_date.isoformat(),
            "subject_line": subject,
            "sections": sections,
            "missed_decision_ids": [m.decision_id for m in agg.missed_decisions],
            "computed_at": now.isoformat(),
        }
        blob = json.dumps(artifact_payload, indent=2).encode("utf-8")
        key = workspace_key(inputs.workspace_id, "briefs", str(brief_id), "brief.json")
        await storage.put(key, blob, "application/json")

        snapshots_written = await write_snapshots(session, agg, computed_at=now)

        # Stamp the brief_id + subject_line into the overview snapshot so the
        # daily_brief endpoint can find the artifact key from one row read.
        await session.execute(
            text(
                "UPDATE dashboard_snapshots "
                "SET metrics = metrics || CAST(:patch AS jsonb) "
                "WHERE workspace_id = :wid "
                "AND snapshot_date = :sd "
                "AND dimension = 'overview'"
            ),
            {
                "wid": inputs.workspace_id,
                "sd": inputs.brief_date,
                "patch": json.dumps(
                    {
                        "brief_id": str(brief_id),
                        "subject_line": subject,
                        "brief_storage_key": key,
                    }
                ),
            },
        )

        if agg.missed_decisions:
            await mark_decisions_surfaced(
                session,
                [UUID(m.decision_id) for m in agg.missed_decisions],
                at=now,
            )

        # Snapshot email-delivery preferences before committing so we can
        # resolve the manager email outside the tx body.
        email_cfg = (workspace.config or {}).get("email", {}) if workspace.config else {}
        email_opted_in = bool(
            email_cfg.get("enabled") and email_cfg.get("manager_daily_brief", True)
        )
        if email_opted_in:
            manager_email = await ws_repo.get_manager_email(inputs.workspace_id)

        await session.commit()

    if email_opted_in and manager_email:
        try:
            from arq.connections import create_pool

            from app.workers.decision_timeout import _redis_settings

            pool = await create_pool(_redis_settings())
            try:
                await pool.enqueue_job(
                    "email_delivery_job",
                    {
                        "workspace_id": str(inputs.workspace_id),
                        "trigger_kind": "daily_brief",
                        "trigger_ref_id": str(brief_id),
                        "recipient_class": "manager",
                        "recipient_addr": manager_email,
                    },
                )
            finally:
                await pool.close()
        except Exception:
            log.warning("daily_brief_email_enqueue_failed", exc_info=True)

    log.info(
        "dashboard_rollup_complete",
        workspace_id=str(inputs.workspace_id),
        brief_date=inputs.brief_date.isoformat(),
        brief_id=str(brief_id),
        snapshots_written=snapshots_written,
    )
    return DashboardRollupResult(brief_artifact_id=brief_id, snapshots_written=snapshots_written)


class DashboardRollup:
    """Class facade for the mini-agent registry."""

    name = "dashboard_rollup"
    trigger = "cron"

    async def run(self, inputs: DashboardRollupInput) -> DashboardRollupResult:
        return await run_dashboard_rollup(inputs)
