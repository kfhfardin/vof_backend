"""Transcript fragment repository."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Speaker, TranscriptFragment


class TranscriptsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        *,
        call_id: UUID,
        workspace_id: UUID,
        speaker: Speaker,
        text: str,
        ts: datetime,
    ) -> TranscriptFragment:
        # Next seq for this call_id
        result = await self.session.execute(
            select(func.coalesce(func.max(TranscriptFragment.seq), 0)).where(
                TranscriptFragment.call_id == call_id
            )
        )
        next_seq = int(result.scalar_one()) + 1
        fragment = TranscriptFragment(
            call_id=call_id,
            workspace_id=workspace_id,
            speaker=speaker,
            text=text,
            seq=next_seq,
            ts=ts,
        )
        self.session.add(fragment)
        await self.session.flush()
        return fragment

    async def list_for_call(self, call_id: UUID) -> list[TranscriptFragment]:
        result = await self.session.execute(
            select(TranscriptFragment)
            .where(TranscriptFragment.call_id == call_id)
            .order_by(TranscriptFragment.seq)
        )
        return list(result.scalars().all())
