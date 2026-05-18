"""Shared pytest fixtures.

The fixture surface is intentionally small — new tests should reuse these,
not roll their own. Adding a new fixture warrants review.
"""

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

# Ensure required env vars are set with safe defaults before any app import.
# Tests that need real values override via monkeypatch.
_TEST_ENV_DEFAULTS = {
    "DEPLOYMENT_PROFILE": "local",
    "ENVIRONMENT": "dev",
    "DATABASE_URL": "postgresql+asyncpg://votf:votf@localhost:5432/votf_app",
    "BRAIN_DATABASE_URL": "postgresql+asyncpg://votf:votf@localhost:5432/votf_brain",
    "REDIS_URL": "redis://localhost:6379/0",
    "S3_BUCKET": "ci-test",
    "S3_ACCESS_KEY": "dummy",
    "S3_SECRET_KEY": "dummy",
    "S3_REGION": "us-east-1",
    "S3_ENDPOINT_URL": "http://localhost:9000",
    "JWT_SECRET": "ci-test-jwt-secret-min-32-bytes-please-please",
    "PUBLIC_BASE_URL": "http://localhost:8000",
    "AGENTPHONE_WEBHOOK_SECRET": "ci-test-webhook-secret",
}
for _k, _v in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_k, _v)

# Force third-party API keys to empty so tests never hit real AP / AgentMail /
# Supermemory accounts (which would exhaust quotas, leak side effects across
# runs, or hit 409s when the account already provisioned a resource). The
# corresponding provider builders fall back to the Fake/Stub implementations
# and the AgentMail provider short-circuits provisioning. Tests that need a
# real client must monkeypatch the relevant variable explicitly.
for _k in ("AGENTPHONE_API_KEY", "AGENTMAIL_API_KEY", "SUPERMEMORY_API_KEY"):
    os.environ[_k] = ""


@pytest.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    """ASGI client against a freshly-built FastAPI app.

    Unit tests should prefer this over making real HTTP requests — it bypasses
    sockets entirely via httpx's ASGITransport.
    """
    from app.factory import build_app

    app = build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
