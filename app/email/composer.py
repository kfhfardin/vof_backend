"""Outbound email composer (Phase 1 §F6).

Renders one of the three Jinja templates under `app/email/templates/` with
the loaded artifact + workspace + recipient_class + tone, then peels off
the first line (which MUST be `Subject: ...`) into ComposedEmail.subject.

Speed variant: pure templating; no LLM call. To replace a template with an
LLM-composed body later, swap the render at the one call site
(email_delivery._compose) and leave the rest of the pipeline unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.email.schemas import ComposedEmail

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    undefined=StrictUndefined,
    autoescape=False,
)


def render_email_template(
    template_name: str,
    *,
    artifact: dict[str, Any],
    workspace: Any,
    recipient_class: str,
    tone: str = "professional",
) -> ComposedEmail:
    tpl = _env.get_template(template_name)
    rendered = tpl.render(
        artifact=artifact,
        workspace=workspace,
        recipient_class=recipient_class,
        tone=tone,
    )
    # First line MUST be `Subject: ...` — the parser pulls it out so the
    # provider's send() can pass subject + body separately.
    lines = rendered.split("\n", 1)
    subject_line = lines[0].strip()
    body = lines[1].strip() if len(lines) > 1 else ""
    if subject_line.lower().startswith("subject:"):
        subject = subject_line[len("subject:"):].strip()
    else:
        workspace_name = getattr(workspace, "name", "your workspace")
        subject = f"Update from {workspace_name}"
        body = rendered
    return ComposedEmail(subject=subject, text=body, html=None)
