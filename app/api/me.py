"""Current-user endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.workspaces_repo import WorkspacesRepo
from app.deps import CurrentUser, get_session
from app.schemas.auth import MeResponse, UserSummary, WorkspaceSummary

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=MeResponse)
async def me(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeResponse:
    ws = None
    if user.workspace_id is not None:
        repo = WorkspacesRepo(session)
        row = await repo.get_by_id(user.workspace_id)
        if row is not None:
            ws = WorkspaceSummary(
                id=row.id,
                name=row.name,
                primary_number=row.primary_number,
                provisioning_state=row.provisioning_state,
            )
    return MeResponse(
        user=UserSummary(
            id=user.id,
            email=user.email,
            role=user.role,
            organization_id=user.organization_id,
            workspace_id=user.workspace_id,
        ),
        workspace=ws,
    )
