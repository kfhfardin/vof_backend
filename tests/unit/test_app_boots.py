"""Walking-skeleton sanity tests.

These prove the foundation is wired correctly:
  - settings load
  - the app builds
  - /health responds
  - reserved namespaces are mounted but return 404 for paths inside them
"""

from httpx import AsyncClient


async def test_health(app_client: AsyncClient) -> None:
    r = await app_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


async def test_auth_endpoints_registered(app_client: AsyncClient) -> None:
    # Real endpoint - missing body returns 400 (validation).
    # Full happy-path signup test lives in tests/integration since it needs Postgres.
    r = await app_client.post("/api/v1/auth/signup")
    assert r.status_code == 400


async def test_reserved_namespaces_return_404_for_unknown_paths(app_client: AsyncClient) -> None:
    # Both namespaces are mounted (the §C10 guard test will later assert this
    # plus role-based rejection). For now: any unknown path inside returns 404.
    r1 = await app_client.get("/api/v1/organizations/00000000-0000-0000-0000-000000000000/anything")
    r2 = await app_client.get("/api/v1/rep/anything")
    assert r1.status_code == 404
    assert r2.status_code == 404


async def test_request_id_round_trips(app_client: AsyncClient) -> None:
    r = await app_client.get("/health", headers={"x-request-id": "test-rid-123"})
    assert r.headers["x-request-id"] == "test-rid-123"


async def test_request_id_generated_when_missing(app_client: AsyncClient) -> None:
    r = await app_client.get("/health")
    assert "x-request-id" in r.headers
    assert len(r.headers["x-request-id"]) > 0
