"""FieldEmployee repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FieldEmployee, User


class FieldEmployeesRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, fe_id: UUID) -> FieldEmployee | None:
        return await self.session.get(FieldEmployee, fe_id)

    async def find_by_phone(self, workspace_id: UUID, phone: str) -> FieldEmployee | None:
        result = await self.session.execute(
            select(FieldEmployee).where(
                FieldEmployee.workspace_id == workspace_id,
                FieldEmployee.phone == phone,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, workspace_id: UUID, email: str) -> FieldEmployee | None:
        """Resolve a Rep within a workspace by email (§F6 inbound reply routing).

        FieldEmployee has no dedicated email column yet; the canonical mapping
        runs through the User table (User.field_employee_id -> FieldEmployee.id,
        with User.email being authoritative). Email is normalized to lowercase.
        """
        if not email:
            return None
        email_n = email.strip().lower()
        result = await self.session.execute(
            select(FieldEmployee)
            .join(User, User.field_employee_id == FieldEmployee.id)
            .where(
                FieldEmployee.workspace_id == workspace_id,
                User.email == email_n,
            )
            .limit(1)
        )
        fe = result.scalar_one_or_none()
        if fe is not None:
            return fe
        # Fallback: free-form profile.email seeded during onboarding/profiling.
        result = await self.session.execute(
            select(FieldEmployee).where(
                FieldEmployee.workspace_id == workspace_id,
                FieldEmployee.profile["email"].astext == email_n,
            )
        )
        return result.scalar_one_or_none()

    async def create_unprofiled(
        self,
        *,
        workspace_id: UUID,
        organization_id: UUID,
        phone: str,
        provisional_name: str | None = None,
    ) -> FieldEmployee:
        """Create a placeholder Rep row for a caller not yet on the roster.

        The profiling sub-flow (LLD §C3) fills in `name`, `role`, `team` and
        flips `profiled=true` once the Manager confirms.
        """
        fe = FieldEmployee(
            workspace_id=workspace_id,
            organization_id=organization_id,
            name=provisional_name or f"Unknown caller {phone[-4:]}" if phone else "Unknown caller",
            phone=phone,
            profiled=False,
        )
        self.session.add(fe)
        await self.session.flush()
        return fe
