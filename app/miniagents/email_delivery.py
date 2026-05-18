"""email_delivery mini-agent (Phase 1 §F6, trigger=queue).

Builds an idempotency key from (workspace_id, trigger_kind, trigger_ref_id,
recipient_class, recipient_addr), short-circuits if we've already sent for
that tuple, then composes (or accepts a precomposed) ComposedEmail and
hands off to the EmailProvider. Writes one EmailMessage audit row per
successful send.

Routing:
  - delivery_route="agentmail"      -> workspace's AgentMail inbox
  - delivery_route="oauth_personal" -> Manager's connected Google OAuth (F9)

Skip outcomes (returned with skipped=True + reason):
  - unknown_workspace
  - inbox_not_provisioned
  - oauth_disconnected
  - already_sent_idempotent
  - no_template_or_precomposed
  - artifact_load_failed
  - send_failed:<ExceptionClass>
  - oauth_connector_unavailable

The mini-agent NEVER raises to the queue worker; arq retries are driven
by the worker shim returning the skip reason as a string.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.db.app_session import app_session
from app.db.repositories.email_messages_repo import EmailMessagesRepo
from app.db.repositories.workspaces_repo import WorkspacesRepo
from app.deps import get_object_store
from app.email.agentmail import AgentMailEmailProvider
from app.email.base import EmailProvider
from app.email.composer import render_email_template
from app.email.oauth_personal import OAuthPersonalEmailProvider
from app.email.schemas import ComposedEmail, SentMessage
from app.logging import get_logger
from app.storage.base import workspace_key

log = get_logger(__name__)

# trigger_kind -> Jinja template filename (no entry for action_item_handler:
# F3 always supplies a `precomposed` ComposedEmail for that path).
_TEMPLATE_MAP: dict[str, str] = {
    "post_call_summary": "post_call_summary.j2",
    "daily_brief": "daily_brief.j2",
    "missed_decisions": "missed_decisions.j2",
}


TriggerKind = Literal[
    "post_call_summary", "daily_brief", "missed_decisions", "action_item_handler"
]
RecipientClass = Literal["manager", "rep", "external_customer"]
DeliveryRoute = Literal["agentmail", "oauth_personal"]


class EmailDeliveryInput(BaseModel):
    workspace_id: UUID
    trigger_kind: TriggerKind
    trigger_ref_id: UUID
    recipient_class: RecipientClass
    recipient_addr: EmailStr
    delivery_route: DeliveryRoute = "agentmail"
    oauth_user_id: UUID | None = None
    idempotency_key: str | None = None
    precomposed: ComposedEmail | None = None


class EmailDeliveryResult(BaseModel):
    skipped: bool = False
    reason: str | None = None
    message_id: str | None = None
    thread_id: str | None = None
    sent_at: Any = None  # datetime; Any keeps Pydantic serialization simple here


def _build_idem_key(inputs: EmailDeliveryInput) -> str:
    raw = (
        f"{inputs.workspace_id}:{inputs.trigger_kind}:{inputs.trigger_ref_id}:"
        f"{inputs.recipient_class}:{str(inputs.recipient_addr).lower()}"
    )
    # 256-char cap on the column is comfortable; hash to keep it stable.
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_message_id(workspace_id: UUID, inputs: EmailDeliveryInput) -> str:
    return f"<{inputs.trigger_kind}.{inputs.trigger_ref_id}@vof-{workspace_id}>"


def _provider_for(route: DeliveryRoute) -> EmailProvider:
    if route == "agentmail":
        return AgentMailEmailProvider()
    return OAuthPersonalEmailProvider()


def _artifact_storage_key(workspace_id: UUID, trigger_kind: TriggerKind, ref_id: UUID) -> str:
    if trigger_kind == "post_call_summary":
        return workspace_key(workspace_id, "calls", str(ref_id), "canonical_summary.json")
    if trigger_kind == "daily_brief":
        # NOTE: This key is the placeholder until F8's dashboard_rollup agent
        # commits to its concrete storage path; both write/read must agree.
        return workspace_key(workspace_id, "briefs", str(ref_id), "brief.json")
    if trigger_kind == "missed_decisions":
        return workspace_key(workspace_id, "briefs", str(ref_id), "missed_decisions.json")
    # action_item_handler always supplies precomposed; we shouldn't get here.
    raise RuntimeError(f"no artifact key configured for trigger_kind={trigger_kind!r}")


async def _load_artifact(workspace_id: UUID, trigger_kind: TriggerKind, ref_id: UUID) -> dict[str, Any]:
    storage = get_object_store()
    key = _artifact_storage_key(workspace_id, trigger_kind, ref_id)
    blob = await storage.get(key)
    return dict(json.loads(blob.decode("utf-8")))


async def _try_load_oauth_credentials(workspace_id: UUID) -> Any | None:
    """Look up the active workspace-wide google_workspace credential.

    Per LLD §F9: one credential per workspace today. Returns None if no
    active (non-revoked) row exists; downstream agent skips with
    `oauth_disconnected`. Token refresh + Gmail API call happen inside
    the F9 connector — this is a preflight existence + revoked check.
    """
    from app.db.repositories.oauth_credentials_repo import OAuthCredentialsRepo

    try:
        async with app_session() as session:
            repo = OAuthCredentialsRepo(session)
            return await repo.get_active(workspace_id, "google_workspace")
    except Exception:
        log.exception(
            "email_delivery_oauth_lookup_failed",
            workspace_id=str(workspace_id),
        )
        return None


async def run(inputs: EmailDeliveryInput) -> EmailDeliveryResult:
    workspace_id = inputs.workspace_id

    # 1. Load workspace.
    async with app_session() as session:
        ws_repo = WorkspacesRepo(session)
        ws = await ws_repo.get_by_id(workspace_id)
        if ws is None:
            log.warning("email_delivery_unknown_workspace", workspace_id=str(workspace_id))
            return EmailDeliveryResult(skipped=True, reason="unknown_workspace")
        email_cfg = (ws.config or {}).get("email", {}) if isinstance(ws.config, dict) else {}
        ws_inbox_id: str | None = ws.email_inbox_id
        ws_inbox_addr: str | None = ws.email_inbox_addr
        ws_tone = str(email_cfg.get("outbound_email_tone", "professional"))
        ws_name = ws.name
        organization_id = ws.organization_id

    # 2. Route preflight.
    if inputs.delivery_route == "agentmail" and not ws_inbox_id:
        log.info(
            "email_delivery_skipped",
            reason="inbox_not_provisioned",
            workspace_id=str(workspace_id),
        )
        return EmailDeliveryResult(skipped=True, reason="inbox_not_provisioned")

    if inputs.delivery_route == "oauth_personal":
        cred = await _try_load_oauth_credentials(workspace_id)
        if cred is None or getattr(cred, "revoked", False):
            return EmailDeliveryResult(skipped=True, reason="oauth_disconnected")

    # 3. Idempotency.
    idem = inputs.idempotency_key or _build_idem_key(inputs)
    async with app_session() as session:
        emails = EmailMessagesRepo(session)
        if await emails.exists_by_idem(idem):
            log.info(
                "email_delivery_skipped",
                reason="already_sent_idempotent",
                idem=idem[:16],
            )
            return EmailDeliveryResult(skipped=True, reason="already_sent_idempotent")

    # 4. Compose (or take the F3-provided precomposed body).
    composed: ComposedEmail
    if inputs.precomposed is not None:
        composed = inputs.precomposed
    else:
        template_name = _TEMPLATE_MAP.get(inputs.trigger_kind)
        if template_name is None:
            log.warning(
                "email_delivery_no_template",
                trigger_kind=inputs.trigger_kind,
            )
            return EmailDeliveryResult(skipped=True, reason="no_template_or_precomposed")
        try:
            artifact = await _load_artifact(
                workspace_id, inputs.trigger_kind, inputs.trigger_ref_id
            )
        except Exception:
            log.exception(
                "email_delivery_artifact_load_failed",
                trigger_kind=inputs.trigger_kind,
                trigger_ref_id=str(inputs.trigger_ref_id),
            )
            return EmailDeliveryResult(skipped=True, reason="artifact_load_failed")

        # Templates only read `workspace.name`; pass a tiny namespace so
        # we don't pin the full ORM object lifetime to template rendering.
        composed = render_email_template(
            template_name,
            artifact=artifact,
            workspace=SimpleNamespace(name=ws_name),
            recipient_class=inputs.recipient_class,
            tone=ws_tone,
        )

    # 5. Send.
    provider = _provider_for(inputs.delivery_route)
    headers: dict[str, str] = {"Message-ID": _build_message_id(workspace_id, inputs)}
    if inputs.delivery_route == "oauth_personal":
        # The EmailProvider Protocol has no workspace_id slot; thread it
        # through headers (the provider strips this before sending).
        headers["X-Workspace-Id"] = str(workspace_id)
    try:
        sent: SentMessage = await provider.send(
            inbox_id=ws_inbox_id if inputs.delivery_route == "agentmail" else None,
            oauth_user_id=inputs.oauth_user_id,
            to=str(inputs.recipient_addr),
            subject=composed.subject,
            text=composed.text,
            html=composed.html,
            reply_to=ws_inbox_addr if inputs.delivery_route == "agentmail" else None,
            headers=headers,
        )
    except NotImplementedError as e:
        log.warning(
            "email_delivery_provider_unavailable",
            route=inputs.delivery_route,
            error=str(e),
        )
        return EmailDeliveryResult(skipped=True, reason="oauth_connector_unavailable")
    except Exception as e:
        # Mini-agent contract: never raise to the queue worker. Surface
        # any provider failure as a skipped outcome with a reason; arq's
        # retry policy can still re-enqueue, and the idempotency_key
        # dedupes the next attempt against the (eventual) successful send.
        log.exception(
            "email_delivery_send_failed",
            route=inputs.delivery_route,
            workspace_id=str(workspace_id),
            trigger_kind=inputs.trigger_kind,
            recipient_class=inputs.recipient_class,
        )
        return EmailDeliveryResult(skipped=True, reason=f"send_failed:{type(e).__name__}")

    # 6. Persist audit row.
    async with app_session() as session:
        emails = EmailMessagesRepo(session)
        await emails.create(
            workspace_id=workspace_id,
            organization_id=organization_id,
            provider=inputs.delivery_route,
            provider_message_id=sent.message_id,
            provider_thread_id=sent.thread_id,
            trigger_kind=inputs.trigger_kind,
            trigger_ref_id=inputs.trigger_ref_id,
            recipient_class=inputs.recipient_class,
            recipient_addr=str(inputs.recipient_addr),
            sent_at=sent.timestamp,
            correlation_idempotency_key=idem,
        )
        await session.commit()

    log.info(
        "email_delivery_sent",
        trigger_kind=inputs.trigger_kind,
        recipient_class=inputs.recipient_class,
        message_id=sent.message_id,
    )
    return EmailDeliveryResult(
        message_id=sent.message_id,
        thread_id=sent.thread_id,
        sent_at=sent.timestamp,
    )
