"""Scheduler mini-agent (Phase 1 F3).

Renders `scheduler_event.j2` from the ActionItem.payload and calls the
Google Calendar connector. The connector signature returns the raw API
JSON dict; we pick out the bits the dispatcher persists as the outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.connectors.google_workspace import (
    GoogleWorkspaceConnector,
    is_google_workspace_configured,
)
from app.db.models import ActionItem, ManagerWorkspace

_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "services" / "action_items" / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    undefined=StrictUndefined,
    autoescape=False,
)


@dataclass(frozen=True)
class SchedulerContext:
    """Per-dispatch context handed to the mini-agent."""

    workspace: ManagerWorkspace
    # The Manager whose OAuth credentials we act under (the workspace owner
    # today; symmetry kept for future per-user credentials).
    oauth_user_id: Any  # UUID; loose-typed to keep this module import-light


class SchedulerMiniAgent:
    name = "scheduler"
    trigger = "queue"

    async def execute(self, ctx: SchedulerContext, action_item: ActionItem) -> dict[str, Any]:
        tone = (ctx.workspace.config or {}).get("email", {}).get(
            "outbound_email_tone", "professional"
        )
        draft = _env.get_template("scheduler_event.j2").render(
            item=action_item,
            payload=action_item.payload or {},
            workspace=ctx.workspace,
            tone=tone,
        )

        if not is_google_workspace_configured():
            # Google is optional. Return the rendered draft so the Manager
            # can manually create the event; dispatcher treats this as "draft
            # ready, no provider link" rather than a failure.
            return {
                "provider_event_id": None,
                "calendar_id": None,
                "event_html_link": None,
                "draft": draft,
                "error": "google_oauth_not_configured",
            }

        connector = GoogleWorkspaceConnector()
        # OAuthRevokedError propagates up to the dispatcher, which marks the
        # row needs_reconnect.
        event = await connector.calendar_create_event(
            ctx.workspace.id, ctx.oauth_user_id, draft
        )
        # `event` is the raw Calendar API JSON; pull only what we persist.
        return {
            "provider_event_id": event.get("id"),
            "calendar_id": event.get("calendarId") or event.get("calendar_id"),
            "event_html_link": event.get("htmlLink"),
            "draft": draft,
        }


__all__ = ["SchedulerContext", "SchedulerMiniAgent"]
