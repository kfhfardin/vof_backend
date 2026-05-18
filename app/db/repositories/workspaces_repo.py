"""Workspaces + organizations repository."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ManagerWorkspace, Organization, ProvisioningState


class OrganizationsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, name: str) -> Organization:
        org = Organization(name=name)
        self.session.add(org)
        await self.session.flush()
        return org


class WorkspacesRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        organization_id: UUID,
        manager_user_id: UUID | None,
        name: str,
    ) -> ManagerWorkspace:
        ws = ManagerWorkspace(
            organization_id=organization_id,
            manager_user_id=manager_user_id,
            name=name,
            provisioning_state="pending",
            config={},
        )
        self.session.add(ws)
        await self.session.flush()
        return ws

    async def get_by_id(self, workspace_id: UUID) -> ManagerWorkspace | None:
        return await self.session.get(ManagerWorkspace, workspace_id)

    async def get_by_primary_number(self, phone: str) -> ManagerWorkspace | None:
        from sqlalchemy import select

        result = await self.session.execute(
            select(ManagerWorkspace).where(ManagerWorkspace.primary_number == phone)
        )
        return result.scalar_one_or_none()

    async def get_by_agentphone_number_id(self, ap_number_id: str) -> ManagerWorkspace | None:
        """Fallback scope resolution when AP webhook omits data.to.

        AP delivers live voice turns with data.to="" but data.numberId set;
        we resolve via the AP number id stored at provisioning.
        """
        from sqlalchemy import select

        if not ap_number_id:
            return None
        result = await self.session.execute(
            select(ManagerWorkspace).where(ManagerWorkspace.agentphone_number_id == ap_number_id)
        )
        return result.scalar_one_or_none()

    async def get_by_agentphone_agent_id(self, ap_agent_id: str) -> ManagerWorkspace | None:
        """Last-resort scope resolution from the top-level agentId on the payload."""
        from sqlalchemy import select

        if not ap_agent_id:
            return None
        result = await self.session.execute(
            select(ManagerWorkspace).where(ManagerWorkspace.agentphone_agent_id == ap_agent_id)
        )
        return result.scalar_one_or_none()

    async def update_provisioning(
        self,
        workspace_id: UUID,
        *,
        primary_number: str | None = None,
        agentphone_agent_id: str | None = None,
        agentphone_number_id: str | None = None,
        provisioning_state: ProvisioningState | None = None,
        config: dict[str, Any] | None = None,
    ) -> ManagerWorkspace:
        ws = await self.get_by_id(workspace_id)
        if ws is None:
            raise RuntimeError(f"workspace {workspace_id} not found")
        if primary_number is not None:
            ws.primary_number = primary_number
        if agentphone_agent_id is not None:
            ws.agentphone_agent_id = agentphone_agent_id
        if agentphone_number_id is not None:
            ws.agentphone_number_id = agentphone_number_id
        if provisioning_state is not None:
            ws.provisioning_state = provisioning_state
        if config is not None:
            ws.config = config
        await self.session.flush()
        return ws

    async def set_manager_user_id(self, workspace_id: UUID, user_id: UUID) -> None:
        ws = await self.get_by_id(workspace_id)
        if ws is None:
            raise RuntimeError(f"workspace {workspace_id} not found")
        ws.manager_user_id = user_id

    async def get_manager_email(self, workspace_id: UUID) -> str | None:
        """Resolve the workspace's manager email (LLD §F8 brief delivery).

        Workspace.manager_user_id -> User.email. Returns None if either side
        is missing (e.g. workspace still provisioning).
        """
        from sqlalchemy import select

        from app.db.models import User

        ws = await self.get_by_id(workspace_id)
        if ws is None or ws.manager_user_id is None:
            return None
        result = await self.session.execute(
            select(User.email).where(User.id == ws.manager_user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email_inbox_id(self, inbox_id: str) -> ManagerWorkspace | None:
        """Resolve workspace by AgentMail inbox_id for inbound reply routing (§F6)."""
        from sqlalchemy import select

        if not inbox_id:
            return None
        result = await self.session.execute(
            select(ManagerWorkspace).where(ManagerWorkspace.email_inbox_id == inbox_id)
        )
        return result.scalar_one_or_none()

    async def update_email_inbox(
        self,
        workspace_id: UUID,
        *,
        inbox_id: str,
        inbox_addr: str,
        domain: str | None,
    ) -> ManagerWorkspace:
        """Persist AgentMail-provisioned inbox identifiers on the workspace."""
        ws = await self.get_by_id(workspace_id)
        if ws is None:
            raise RuntimeError(f"workspace {workspace_id} not found")
        ws.email_inbox_id = inbox_id
        ws.email_inbox_addr = inbox_addr
        ws.email_domain = domain
        await self.session.flush()
        return ws
