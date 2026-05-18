"""Action-item handler dispatcher (Phase 1 F3).

Cron-style job per Workspace (every ~60s). Picks up
`ActionItem(status=approved, handler != none)` and runs the matching
mini-agent. Outcome / error / attempts are persisted back on the row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.connectors.base import OAuthRevokedError
from app.db.app_session import app_session
from app.db.models import ActionItem, ActionItemStatus, ManagerWorkspace
from app.db.repositories.action_items_repo import ActionItemsRepo
from app.db.repositories.oauth_credentials_repo import OAuthCredentialsRepo
from app.db.repositories.workspaces_repo import WorkspacesRepo
from app.logging import get_logger
from app.miniagents.email_drafter import EmailDrafterContext, EmailDrafterMiniAgent
from app.miniagents.scheduler import SchedulerContext, SchedulerMiniAgent

log = get_logger(__name__)

MAX_HANDLER_ATTEMPTS = 3


async def _run_one(
    *,
    repo: ActionItemsRepo,
    workspace: ManagerWorkspace,
    oauth_user_id: UUID | None,
    item: ActionItem,
) -> None:
    """Execute a single ActionItem handler; persist outcome."""
    attempts = (item.handler_attempts or 0) + 1
    now = datetime.now(UTC)

    if item.handler != "none" and oauth_user_id is None:
        # No connected Google credential at all — Manager needs to OAuth.
        await repo.update_handler_outcome(
            item,
            status="needs_reconnect",
            executed_at=now,
            error="no_oauth_credentials",
            attempts=attempts,
        )
        return

    try:
        if item.handler == "scheduler":
            outcome = await SchedulerMiniAgent().execute(
                SchedulerContext(workspace=workspace, oauth_user_id=oauth_user_id), item
            )
        elif item.handler == "email_drafter":
            outcome = await EmailDrafterMiniAgent().execute(
                EmailDrafterContext(workspace=workspace, oauth_user_id=oauth_user_id), item
            )
        else:
            log.info(
                "action_item_dispatcher_skip_handler_none",
                action_item_id=str(item.id),
            )
            return
    except OAuthRevokedError as e:
        await repo.update_handler_outcome(
            item,
            status="needs_reconnect",
            executed_at=now,
            error=f"oauth_revoked: {e}",
            attempts=attempts,
        )
        return
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        log.exception(
            "action_item_handler_failed",
            action_item_id=str(item.id),
            attempts=attempts,
        )
        next_status = "failed" if attempts >= MAX_HANDLER_ATTEMPTS else "approved"
        await repo.update_handler_outcome(
            item,
            status=next_status,
            executed_at=now,
            error=err,
            attempts=attempts,
        )
        return

    # In-band errors (handler returns {"error": "..."} for non-exceptional
    # cases like a missing recipient or Google not configured).
    err_code = outcome.get("error") if isinstance(outcome, dict) else None
    if err_code:
        # Map known soft-errors to the appropriate terminal status. Anything
        # we don't recognize falls through to `failed`.
        if err_code == "google_oauth_not_configured":
            soft_status: ActionItemStatus = "needs_reconnect"
        else:
            soft_status = "failed"
        await repo.update_handler_outcome(
            item,
            status=soft_status,
            outcome=outcome,
            executed_at=now,
            error=err_code,
            attempts=attempts,
        )
        return

    await repo.update_handler_outcome(
        item,
        status="done",
        outcome=outcome,
        executed_at=now,
        attempts=attempts,
    )


async def action_item_dispatcher_job(ctx: dict[str, Any], workspace_id_str: str) -> str:
    """arq entry point. Drains approved items for the given Workspace.

    Invoked by the cron `_action_item_dispatcher_cron` (fans out to all
    active workspaces every 60s; see app/workers/settings.py).
    """
    workspace_id = UUID(workspace_id_str)

    async with app_session() as session:
        ws_repo = WorkspacesRepo(session)
        workspace = await ws_repo.get_by_id(workspace_id)
        if workspace is None:
            log.warning("action_item_dispatcher_workspace_missing", workspace_id=workspace_id_str)
            return "no_workspace"

        repo = ActionItemsRepo(session)
        items = await repo.list_approved_with_handler(workspace_id, limit=50)
        if not items:
            return "idle"

        # Resolve the oauth_user_id once per dispatch — the active Google
        # credential row carries `connected_by_user_id`. If absent, every
        # handler item flips to needs_reconnect (see _run_one).
        oauth_repo = OAuthCredentialsRepo(session)
        creds = await oauth_repo.get_active(workspace_id, "google_workspace")
        oauth_user_id = creds.connected_by_user_id if creds is not None else None

        processed = 0
        for item in items:
            await _run_one(
                repo=repo,
                workspace=workspace,
                oauth_user_id=oauth_user_id,
                item=item,
            )
            processed += 1

        await session.commit()
        log.info(
            "action_item_dispatcher_done",
            workspace_id=workspace_id_str,
            processed=processed,
        )
        return f"processed:{processed}"


async def action_item_dispatcher_cron(ctx: dict[str, Any]) -> str:
    """Cron fan-out: enqueue per-workspace dispatcher runs every minute.

    Cheap: one `SELECT id` per minute over `manager_workspaces`. We don't
    set unique job_ids — skipping a tick is fine because idle calls are no-ops.
    """
    from arq.connections import ArqRedis, create_pool
    from sqlalchemy import select

    from app.workers.decision_timeout import _redis_settings

    async with app_session() as session:
        result = await session.execute(select(ManagerWorkspace.id))
        workspace_ids = [row[0] for row in result.all()]

    if not workspace_ids:
        return "no_workspaces"

    pool: ArqRedis | None = ctx.get("redis") if isinstance(ctx, dict) else None
    close_pool = False
    if pool is None:
        pool = await create_pool(_redis_settings())
        close_pool = True
    try:
        for wid in workspace_ids:
            await pool.enqueue_job("action_item_dispatcher_job", str(wid))
    finally:
        if close_pool:
            await pool.aclose()
    return f"fanout:{len(workspace_ids)}"
