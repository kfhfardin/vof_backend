"""arq worker configuration.

Run with:
    arq app.workers.settings.WorkerSettings

Phase 0 hosts every queue's handlers in a single worker class. Adding a new
queue handler is one import + one entry in `functions`. Splitting into
per-queue workers (one process per queue) is a config change only.

Cron jobs (Phase 1):
  - `dashboard_rollup_dispatcher_job` at 07:00 UTC daily fans out to every
    workspace (LLD §F8). The per-workspace `dashboard_rollup_job` is in
    `functions` so the dispatcher's enqueues can pick it up.
  - `action_item_dispatcher_cron` every minute fans out per-workspace
    `action_item_dispatcher_job` runs (LLD §F3) which drain approved items.
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq.cron import cron

from app.workers.action_item_dispatcher import (
    action_item_dispatcher_cron,
    action_item_dispatcher_job,
)
from app.workers.correction_cascade import correction_cascade_job
from app.workers.dashboard_rollup import (
    dashboard_rollup_dispatcher_job,
    dashboard_rollup_job,
)
from app.workers.decision_timeout import _redis_settings, decision_timeout_job
from app.workers.email_delivery import email_delivery_job
from app.workers.post_call import post_call_job


async def _startup(ctx: dict[str, Any]) -> None:
    # Mirror app/lifespan.py - warm up registries on worker boot.
    from app.services import intake_extractors as _ie  # noqa: F401
    from app.skills import load_all_skills

    load_all_skills()


async def _shutdown(ctx: dict[str, Any]) -> None:
    return None


class WorkerSettings:
    redis_settings = _redis_settings()
    on_startup = _startup
    on_shutdown = _shutdown
    functions: ClassVar[list[Any]] = [
        decision_timeout_job,
        correction_cascade_job,
        post_call_job,
        action_item_dispatcher_job,
        dashboard_rollup_job,
        email_delivery_job,
    ]
    cron_jobs: ClassVar[list[Any]] = [
        # Dispatcher: every day at 07:00 UTC. Enqueues one
        # `dashboard_rollup_job` per workspace for yesterday's date.
        cron(
            dashboard_rollup_dispatcher_job,
            hour={7},
            minute={0},
            run_at_startup=False,
            unique=True,
        ),
        # F3 action-item dispatcher: every minute, fans out to every
        # workspace. Each per-workspace run drains `status=approved` rows
        # whose handler != "none".
        cron(
            action_item_dispatcher_cron,
            second={0},
            run_at_startup=False,
            unique=True,
        ),
    ]
