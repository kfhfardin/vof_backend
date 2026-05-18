"""Workspace provisioning - the §C1 signup flow.

The critical sequence: commit org/workspace/user inside one transaction,
THEN do external side effects (AP number, brain schema, memory namespace).
If a side effect fails, the workspace row exists with provisioning_state set
appropriately; a retry worker can finish later. We never pair a transaction
rollback with a paid-for AP number that would leak.

Phase 1 §F6 adds an AgentMail inbox provisioning side effect after the AP
number step. Failure is non-fatal: the workspace still becomes usable for
calls; the email columns simply remain unset and email_delivery will skip
with `reason="inbox_not_provisioned"` until a future retry succeeds.
"""

import os
import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.base import BrainProvider
from app.db.models import ManagerWorkspace, User
from app.db.repositories.users_repo import UsersRepo
from app.db.repositories.workspaces_repo import OrganizationsRepo, WorkspacesRepo
from app.email.agentmail import AgentMailEmailProvider
from app.logging import get_logger
from app.memory.base import CallerMemoryProvider
from app.security.hashing import hash_password
from app.services.auth_service import AuthService, IssuedTokens, ensure_email_available
from app.telephony.base import TelephonyProvider

log = get_logger(__name__)


@dataclass
class SignupResult:
    user: User
    workspace: ManagerWorkspace
    tokens: IssuedTokens


class WorkspaceProvisioningService:
    def __init__(
        self,
        session: AsyncSession,
        telephony: TelephonyProvider,
        memory: CallerMemoryProvider,
        brain: BrainProvider,
    ) -> None:
        self.session = session
        self.telephony = telephony
        self.memory = memory
        self.brain = brain

    async def signup(
        self,
        *,
        email: str,
        password: str,
        workspace_name: str,
    ) -> SignupResult:
        email_n = email.lower()
        await ensure_email_available(self.session, email_n)

        organizations = OrganizationsRepo(self.session)
        workspaces = WorkspacesRepo(self.session)
        users = UsersRepo(self.session)

        # 1. Commit the row backbone in one transaction
        org = await organizations.create(name=f"{workspace_name} (auto)")
        ws = await workspaces.create(
            organization_id=org.id,
            manager_user_id=None,  # set after user is created
            name=workspace_name,
        )
        user = await users.create(
            organization_id=org.id,
            workspace_id=ws.id,
            email=email_n,
            password_hash=hash_password(password),
            role="manager",
        )
        await workspaces.set_manager_user_id(ws.id, user.id)
        await self.session.commit()
        await self.session.refresh(ws)
        await self.session.refresh(user)

        log.info("signup_committed", user_id=str(user.id), workspace_id=str(ws.id))

        # 2. External side effects - failure here does NOT roll back the DB row.
        await self._provision_externals(ws)

        # 3. Issue tokens
        auth = AuthService(self.session)
        tokens = await auth._issue_pair(user)
        await self.session.commit()
        return SignupResult(user=user, workspace=ws, tokens=tokens)

    async def _provision_externals(self, ws: ManagerWorkspace) -> None:
        workspaces = WorkspacesRepo(self.session)
        try:
            provisioned = await self.telephony.provision_number(ws.name)
            await workspaces.update_provisioning(
                ws.id,
                primary_number=provisioned.phone_number,
                agentphone_agent_id=provisioned.ap_agent_id,
                agentphone_number_id=provisioned.ap_number_id,
                provisioning_state="number_pending",  # still need brain + memory
            )
        except Exception:
            log.exception("ap_provision_failed", workspace_id=str(ws.id))
            await workspaces.update_provisioning(ws.id, provisioning_state="number_pending")
            await self.session.commit()
            # Don't raise - signup still succeeds; a retry worker handles this.
            return

        try:
            await self.brain.ensure_schema(ws.id)
            await self.memory.ensure_namespace(ws.id)
            await workspaces.update_provisioning(ws.id, provisioning_state="ready")
        except Exception:
            log.exception("brain_or_memory_provision_failed", workspace_id=str(ws.id))
            await workspaces.update_provisioning(ws.id, provisioning_state="number_pending")
        finally:
            await self.session.commit()
            await self.session.refresh(ws)

        # Phase 1 §F6: provision an AgentMail inbox for outbound + inbound email.
        # Non-fatal: failures leave the email columns NULL; email_delivery will
        # skip with `inbox_not_provisioned` until a retry succeeds.
        try:
            # email_inbox_id column is String(64); slug is the part the
            # stub also embeds, so cap at 48 chars to leave headroom.
            slug = (_slugify(ws.name) or f"workspace-{str(ws.id)[:8]}")[:48]
            domain = os.environ.get("EMAIL_DOMAIN") or None
            provider = AgentMailEmailProvider()
            inbox = await provider.provision_workspace_inbox(
                workspace_id=ws.id, slug=slug, domain=domain
            )
            await workspaces.update_email_inbox(
                ws.id,
                inbox_id=inbox.inbox_id,
                inbox_addr=inbox.address,
                domain=domain,
            )
            await self.session.commit()
            await self.session.refresh(ws)
        except Exception:
            log.warning("agentmail_provision_failed", workspace_id=str(ws.id), exc_info=True)


_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")
