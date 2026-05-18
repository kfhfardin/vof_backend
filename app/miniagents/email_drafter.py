"""Email-drafter mini-agent (Phase 1 F3).

Renders `email_drafter_message.j2` and sends via the personal Gmail OAuth
route. The connector returns the raw Gmail API JSON; we pick out the
provider IDs that the dispatcher persists as the outcome.
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
class EmailDrafterContext:
    workspace: ManagerWorkspace
    # The Manager whose OAuth credentials we act under (the workspace owner
    # today; symmetry kept for future per-user credentials).
    oauth_user_id: Any  # UUID; loose-typed to keep this module import-light


def _split_subject_body(rendered: str) -> tuple[str, str]:
    """The template's first line is `Subject: ...`."""
    lines = rendered.splitlines()
    subject = ""
    body_start = 0
    for i, line in enumerate(lines):
        if line.lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:]).strip()
    return subject, body


class EmailDrafterMiniAgent:
    name = "email_drafter"
    trigger = "queue"

    async def execute(self, ctx: EmailDrafterContext, action_item: ActionItem) -> dict[str, Any]:
        tone = (ctx.workspace.config or {}).get("email", {}).get(
            "outbound_email_tone", "professional"
        )
        rendered = _env.get_template("email_drafter_message.j2").render(
            item=action_item,
            payload=action_item.payload or {},
            workspace=ctx.workspace,
            tone=tone,
        )
        subject, body = _split_subject_body(rendered)
        draft = {"subject": subject, "body": body, "raw": rendered}

        recipient = (action_item.payload or {}).get("recipient_email")
        if not recipient:
            # No recipient on the payload — Manager should PATCH it in first.
            return {"draft": draft, "error": "missing_recipient"}

        if not is_google_workspace_configured():
            # Google is optional. Surface the draft + a clear skip marker so
            # the Manager can copy/paste from the UI; downstream handlers
            # treat this as "ready to send via another channel".
            return {
                "draft": draft,
                "error": "google_oauth_not_configured",
                "sent_to": None,
            }

        connector = GoogleWorkspaceConnector()
        # OAuthRevokedError propagates up to the dispatcher, which marks the
        # row needs_reconnect.
        sent = await connector.gmail_send(
            ctx.workspace.id,
            ctx.oauth_user_id,
            to=recipient,
            subject=subject,
            body_text=body,
        )
        # `sent` is the raw Gmail API JSON: {id, threadId, labelIds, ...}
        return {
            "message_id": sent.get("id"),
            "thread_id": sent.get("threadId"),
            "draft": draft,
            "sent_to": recipient,
        }


__all__ = ["EmailDrafterContext", "EmailDrafterMiniAgent"]
