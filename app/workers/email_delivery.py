"""arq wrapper for the email_delivery mini-agent.

Mini-agent lives in `app/miniagents/email_delivery.py`. This thin shim
adapts arq's `(ctx, *args)` calling convention into the mini-agent's
typed input.
"""

from __future__ import annotations

from typing import Any

from app.logging import get_logger
from app.miniagents.email_delivery import EmailDeliveryInput
from app.miniagents.email_delivery import run as run_email_delivery

log = get_logger(__name__)


async def email_delivery_job(ctx: dict[str, Any], inputs_dict: dict[str, Any]) -> str:
    inputs = EmailDeliveryInput.model_validate(inputs_dict)
    result = await run_email_delivery(inputs)
    log.info(
        "email_delivery_job_complete",
        workspace_id=str(inputs.workspace_id),
        trigger_kind=inputs.trigger_kind,
        skipped=result.skipped,
        reason=result.reason,
    )
    return "ok" if not result.skipped else f"skipped:{result.reason}"
