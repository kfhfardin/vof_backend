"""Brain DB async session factory. Always pinned to a Workspace schema."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.settings import get_settings


@lru_cache(maxsize=1)
def _engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.brain_database_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def _factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_engine(), expire_on_commit=False)


@asynccontextmanager
async def brain_session(workspace_id: UUID) -> AsyncIterator[AsyncSession]:
    """Open a brain-DB session pinned to `brain_w_{workspace_id}` schema.

    The SET LOCAL search_path is the workspace isolation boundary — bypassing
    this wrapper is the only way to read cross-Workspace brain data, which is
    why a lint check rejects raw SQL outside app/db/.
    """
    schema = f"brain_w_{workspace_id.hex}"
    async with _factory()() as session:
        await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        yield session
