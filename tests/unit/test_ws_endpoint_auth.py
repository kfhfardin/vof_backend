"""WS endpoint auth surface - the no-Redis path.

  - /ws/token requires JWT (401 without)
  - /ws/live closes 4401 when ?token= is empty (claim_ws_token short-circuits
    before touching Redis when the token string is empty)

The Redis-touching paths (valid token round-trip, expired token, scope
mismatch on a real token) live in tests/integration/test_ws_live.py.
"""

import pytest
from httpx import AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.factory import build_app


async def test_token_endpoint_requires_auth(app_client: AsyncClient) -> None:
    r = await app_client.post("/api/v1/workspaces/00000000-0000-0000-0000-000000000000/ws/token")
    assert r.status_code == 401


def test_ws_closes_when_token_missing() -> None:
    app = build_app()
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/v1/workspaces/00000000-0000-0000-0000-000000000000/ws/live"):
            pass
    assert exc.value.code == 4401
