"""Integration tests: signup -> login -> /me -> refresh -> logout.

Requires docker compose up (or CI Postgres). Run via: `make integration`.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def _signup(client: AsyncClient, email: str, password: str, ws_name: str = "Acme Sales") -> dict:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "workspace_name": ws_name},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_signup_happy_path(integration_client: AsyncClient) -> None:
    body = await _signup(integration_client, "owner@acmetest.com", "correct horse battery staple", "Acme")
    assert body["user"]["email"] == "owner@acmetest.com"
    assert body["user"]["role"] == "manager"
    assert body["workspace"]["name"] == "Acme"
    # The fake telephony provider returns a synthetic E.164 number.
    assert body["workspace"]["primary_number"].startswith("+1")
    assert body["workspace"]["provisioning_state"] in ("ready", "number_pending")
    assert body["tokens"]["access_token"]
    assert body["tokens"]["refresh_token"]
    assert body["tokens"]["token_type"] == "Bearer"


async def test_signup_email_taken_returns_409(integration_client: AsyncClient) -> None:
    await _signup(integration_client, "dup@acmetest.com", "correct horse battery staple")
    r = await integration_client.post(
        "/api/v1/auth/signup",
        json={"email": "dup@acmetest.com", "password": "correct horse battery staple", "workspace_name": "X"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


async def test_login_returns_tokens_and_me_works(integration_client: AsyncClient) -> None:
    await _signup(integration_client, "login@acmetest.com", "correct horse battery staple")
    r = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": "login@acmetest.com", "password": "correct horse battery staple"},
    )
    assert r.status_code == 200, r.text
    tokens = r.json()

    me = await integration_client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["user"]["email"] == "login@acmetest.com"
    assert body["user"]["role"] == "manager"
    assert body["workspace"] is not None


async def test_login_wrong_password_returns_403(integration_client: AsyncClient) -> None:
    await _signup(integration_client, "bad@acmetest.com", "correct horse battery staple")
    r = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": "bad@acmetest.com", "password": "wrong"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


async def test_refresh_rotates_token(integration_client: AsyncClient) -> None:
    body = await _signup(integration_client, "rot@acmetest.com", "correct horse battery staple")
    first_refresh = body["tokens"]["refresh_token"]

    r1 = await integration_client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert r1.status_code == 200, r1.text
    second = r1.json()
    assert second["access_token"] != body["tokens"]["access_token"]
    assert second["refresh_token"] != first_refresh

    # Using the old refresh token after rotation triggers reuse-detection (403).
    r2 = await integration_client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert r2.status_code == 403, r2.text
    assert "reuse" in r2.json()["error"]["message"].lower()


async def test_logout_revokes_refresh(integration_client: AsyncClient) -> None:
    body = await _signup(integration_client, "lo@acmetest.com", "correct horse battery staple")
    rt = body["tokens"]["refresh_token"]

    r = await integration_client.post("/api/v1/auth/logout", json={"refresh_token": rt})
    assert r.status_code == 204

    # Subsequent refresh with revoked token: reuse-detection or invalid_token.
    r2 = await integration_client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
    assert r2.status_code in (401, 403)


async def test_unauthenticated_me_returns_401(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/me")
    assert r.status_code == 401
