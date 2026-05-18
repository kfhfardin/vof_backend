"""Integration tests: run real Alembic migrations against the compose Postgres.

Marked `integration` - requires docker compose (or CI services).
Run via: `make integration` or `pytest tests/integration -m integration`.
"""

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic(target: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run scripts.alembic_wrapper for `target` (app|brain) with given args."""
    env = os.environ.copy()
    return subprocess.run(
        [sys.executable, "-m", "scripts.alembic_wrapper", target, *args],
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _sync_url(env_name: str) -> str:
    return os.environ[env_name].replace("postgresql+asyncpg://", "postgresql://")


@pytest.mark.integration
def test_app_migration_upgrades_then_downgrades_cleanly() -> None:
    # Start clean
    down = _alembic("app", "downgrade", "base")
    assert down.returncode == 0, f"downgrade failed: {down.stderr}"

    # Upgrade
    up = _alembic("app", "upgrade", "head")
    assert up.returncode == 0, f"upgrade failed: {up.stderr}"

    # Inspect schema
    with psycopg.connect(_sync_url("DATABASE_URL"), connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"
        )
        tables = [r[0] for r in cur.fetchall()]
        assert "organizations" in tables
        assert "manager_workspaces" in tables
        assert "users" in tables

        # FK from workspaces.organization_id -> organizations.id
        cur.execute(
            """
            SELECT tc.constraint_name
              FROM information_schema.table_constraints tc
             WHERE tc.table_name='manager_workspaces' AND tc.constraint_type='FOREIGN KEY'
            """
        )
        fks = {r[0] for r in cur.fetchall()}
        assert any("organization" in fk for fk in fks)

        # role check constraint
        cur.execute(
            """
            SELECT pg_get_constraintdef(c.oid)
              FROM pg_constraint c
             WHERE conname='ck_users_role'
                OR conname LIKE 'ck_users_%role'
            """
        )
        row = cur.fetchone()
        assert row, "role check constraint not found on users"
        assert "manager" in row[0] and "org_admin" in row[0] and "rep" in row[0]

    # Round-trip back down — then restore to head so every test that runs
    # after this one (in any order) finds the schema intact. Leaving the DB
    # at "base" empties every table and breaks the rest of the integration
    # suite, since `_truncate_app_db_between_tests` assumes the schema is
    # already there.
    down2 = _alembic("app", "downgrade", "base")
    assert down2.returncode == 0, f"final downgrade failed: {down2.stderr}"
    restore = _alembic("app", "upgrade", "head")
    assert restore.returncode == 0, f"restore-to-head failed: {restore.stderr}"


@pytest.mark.integration
def test_brain_migration_enables_pgvector() -> None:
    up = _alembic("brain", "upgrade", "head")
    assert up.returncode == 0, f"brain upgrade failed: {up.stderr}"

    with psycopg.connect(_sync_url("BRAIN_DATABASE_URL"), connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname='vector'")
        assert cur.fetchone() is not None
