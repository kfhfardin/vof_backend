"""End-to-end WS test: mint token -> connect -> receive snapshot ->
publish a transcript frame to the bus -> assert client receives it.

Requires docker compose (Postgres + Redis).
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from app.db.models import ManagerWorkspace, Organization, User
from app.factory import build_app
from app.realtime.bus import publish_frame
from app.realtime.redis_client import issue_ws_token
from app.schemas.ws_frames import TranscriptFragmentFrame
from app.security.hashing import hash_password
from app.settings import get_settings

pytestmark = pytest.mark.integration


async def _seed_workspace() -> tuple[uuid.UUID, uuid.UUID]:
    """Insert org + workspace + manager user; return (user_id, workspace_id)."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            org = Organization(name="WS Org")
            session.add(org)
            await session.flush()
            ws = ManagerWorkspace(organization_id=org.id, name="WS Workspace", provisioning_state="ready")
            session.add(ws)
            await session.flush()
            user = User(
                organization_id=org.id,
                workspace_id=ws.id,
                email=f"ws-{uuid.uuid4().hex[:8]}@testlocal.com",
                password_hash=hash_password("correct horse battery staple"),
                role="manager",
            )
            session.add(user)
            await session.commit()
            return user.id, ws.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ws_round_trip_receives_published_frame() -> None:
    user_id, workspace_id = await _seed_workspace()
    token = await issue_ws_token(user_id=str(user_id), workspace_id=str(workspace_id))

    app = build_app()
    client = TestClient(app)

    with client.websocket_connect(f"/api/v1/workspaces/{workspace_id}/ws/live?token={token}") as ws:
        # Expect the initial snapshot first.
        snapshot_raw = ws.receive_text()
        snapshot = json.loads(snapshot_raw)
        assert snapshot["type"] == "snapshot"
        assert isinstance(snapshot["calls"], list)

        # Publish a transcript fragment on the bus; subscriber should forward.
        frame = TranscriptFragmentFrame(
            call_id=uuid.uuid4(),
            speaker="caller",
            text="hello from integration test",
            seq=1,
            ts=datetime.now(UTC),
        ).model_dump(mode="json")

        async def _publish_after_delay() -> None:
            await asyncio.sleep(0.3)
            await publish_frame(workspace_id, frame)

        # Schedule the publish on the event loop the WS test client uses.
        task = asyncio.create_task(_publish_after_delay())

        # Starlette's WebSocketTestSession.receive_text() is sync and has no
        # timeout kwarg; run it in an executor so we can bound it from the
        # async test side (pub/sub is async and could otherwise wedge the
        # test if the bus loses the frame).
        loop = asyncio.get_running_loop()
        received_raw = await asyncio.wait_for(
            loop.run_in_executor(None, ws.receive_text), timeout=5
        )
        await task
        received = json.loads(received_raw)
        assert received["type"] == "transcript.fragment"
        assert received["text"] == "hello from integration test"


@pytest.mark.asyncio
async def test_ws_rejects_token_for_other_workspace() -> None:
    user_id, workspace_id = await _seed_workspace()
    _, other_workspace_id = await _seed_workspace()
    token = await issue_ws_token(user_id=str(user_id), workspace_id=str(workspace_id))

    app = build_app()
    client = TestClient(app)
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/v1/workspaces/{other_workspace_id}/ws/live?token={token}"):
            pass
    assert exc.value.code == 4403
