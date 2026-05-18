"""Call artifact repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ArtifactKind, CallArtifact


class CallArtifactsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        call_id: UUID,
        workspace_id: UUID,
        kind: ArtifactKind,
        storage_key: str,
        bytes_: int,
        content_type: str,
        sha256: str,
    ) -> CallArtifact:
        artifact = CallArtifact(
            call_id=call_id,
            workspace_id=workspace_id,
            kind=kind,
            storage_key=storage_key,
            bytes=bytes_,
            content_type=content_type,
            sha256=sha256,
        )
        self.session.add(artifact)
        await self.session.flush()
        return artifact

    async def get_by_kind(self, call_id: UUID, kind: ArtifactKind) -> CallArtifact | None:
        result = await self.session.execute(
            select(CallArtifact)
            .where(CallArtifact.call_id == call_id, CallArtifact.kind == kind)
            .order_by(CallArtifact.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_call(self, call_id: UUID) -> list[CallArtifact]:
        result = await self.session.execute(
            select(CallArtifact)
            .where(CallArtifact.call_id == call_id)
            .order_by(CallArtifact.created_at.desc())
        )
        return list(result.scalars().all())
