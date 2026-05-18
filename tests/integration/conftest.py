"""Fixtures specific to integration tests.

Each test starts with the DB clean. We truncate-cascade between tests
rather than rolling back transactions because async sessions + nested
savepoints get unhappy with async fixtures.

After the whole suite finishes, the `_reseed_for_live_calls` session
finalizer re-runs the production onboarding flow (Org + Manager +
Workspace at +14783304859 + Rep at +17653506634 + sales/car intake) so
the operator can dial +14783304859 immediately without re-running the
standalone seed script.
"""

import asyncio
from collections.abc import AsyncIterator, Generator

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient


def _sync_url(env_name: str) -> str:
    import os

    return os.environ[env_name].replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture(scope="session", autouse=True)
def _reseed_for_live_calls() -> Generator[None, None, None]:
    """Session-scope finalizer: after every per-test truncate, re-seed
    the production workspace so live phone calls work immediately.

    Runs even if tests failed — best-effort with try/except + clear log.
    No-op if Postgres isn't reachable (so unit-test-only invocations
    don't break here).
    """
    yield
    import os
    import sys

    if "DATABASE_URL" not in os.environ:
        return

    try:
        from tests.integration._onboarding import (
            PROD_AP_NUMBER,
            onboard_production_workspace,
        )

        async def _run() -> None:
            # Tests left asyncpg connections bound to a now-closed pytest
            # event loop. We're about to open a fresh loop via asyncio.run,
            # so dispose the cached engines first — the next session() call
            # rebuilds them against the current loop.
            from app.db import app_session as _aps
            from app.db import brain_session as _bs

            try:
                await _aps._engine().dispose()
            except Exception:
                pass
            try:
                _aps._engine.cache_clear()
                _aps._factory.cache_clear()
                _bs._engine.cache_clear()
                _bs._factory.cache_clear()
            except Exception:
                pass

            await onboard_production_workspace()

        asyncio.run(_run())
        sys.stderr.write(
            f"\n[reseed] production workspace re-seeded at {PROD_AP_NUMBER}; "
            "you can dial it now.\n"
        )
    except Exception as e:
        sys.stderr.write(
            f"\n[reseed] WARNING: failed to re-seed production workspace: "
            f"{type(e).__name__}: {e}\n"
            "         Run `uv run python -m scripts.seed_test_workspace "
            "--ap-number +14783304859` manually to restore.\n"
        )


@pytest.fixture(autouse=True)
def _truncate_app_db_between_tests() -> None:
    """Truncate every table in the app DB before each integration test, and
    clear the cached SQLAlchemy engine factories.

    pytest-asyncio creates a fresh event loop per test (function scope), but
    `app.db.app_session._engine()` and `_factory()` are `@lru_cache`'d at
    module level — the cached AsyncEngine is pinned to whichever loop first
    constructed it. Clearing the cache here forces each test to build its
    own engine against its own loop, which avoids the "Task ... got Future
    ... attached to a different loop" failures after test_migrations runs.
    """
    import os

    # Clear the engine caches — each test rebuilds against its own loop.
    try:
        from app.db import app_session as _aps
        from app.db import brain_session as _bs

        _aps._engine.cache_clear()
        _aps._factory.cache_clear()
        _bs._engine.cache_clear()
        _bs._factory.cache_clear()
    except Exception:
        pass

    if "DATABASE_URL" not in os.environ:
        return
    try:
        with psycopg.connect(_sync_url("DATABASE_URL"), connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT tablename FROM pg_tables
                 WHERE schemaname = 'public' AND tablename <> 'alembic_version'
                """
            )
            tables = [r[0] for r in cur.fetchall()]
            if tables:
                cur.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE")
                conn.commit()
    except psycopg.OperationalError:
        pytest.skip("Postgres not reachable; integration tests require docker compose up")


@pytest.fixture
async def integration_client() -> AsyncIterator[AsyncClient]:
    # Re-import after env is loaded so settings binds against real URLs
    from app.factory import build_app

    app = build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
