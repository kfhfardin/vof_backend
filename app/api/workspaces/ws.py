"""Workspace WebSocket endpoints.

  POST /workspaces/{wid}/ws/token  - mint a 30s one-time token (requires JWT)
  WS   /workspaces/{wid}/ws/live   - upgrade; ?token=<one-time> for auth

The two-step pattern exists because browsers can't send Authorization
headers on a WS upgrade. The token is stored in Redis with TTL 30s and
deleted on first use.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, WebSocket, status
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from app.db.app_session import app_session
from app.deps import CurrentUser, require_workspace_access
from app.logging import get_logger
from app.realtime.redis_client import claim_ws_token, issue_ws_token
from app.realtime.ws_hub import WorkspaceWSConnection

router = APIRouter(prefix="/workspaces/{workspace_id}/ws", tags=["realtime"])
log = get_logger(__name__)


class WSTokenResponse(BaseModel):
    token: str
    ttl_seconds: int


@router.post(
    "/token",
    status_code=status.HTTP_201_CREATED,
    response_model=WSTokenResponse,
    dependencies=[Depends(require_workspace_access)],
)
async def issue_token(
    workspace_id: UUID,
    user: CurrentUser,
) -> WSTokenResponse:
    token = await issue_ws_token(user_id=str(user.id), workspace_id=str(workspace_id))
    return WSTokenResponse(token=token, ttl_seconds=30)


@router.websocket("/live")
async def ws_live(
    websocket: WebSocket,
    workspace_id: UUID,
    token: Annotated[str | None, Query()] = None,
) -> None:
    """Multiplexed live frame stream for one Workspace."""
    claimed = await claim_ws_token(token or "")
    if claimed is None:
        await websocket.close(code=4401, reason="invalid or expired ws token")
        return
    _user_id, claimed_workspace = claimed
    if claimed_workspace != str(workspace_id):
        await websocket.close(code=4403, reason="ws token scope mismatch")
        return

    async with app_session() as session:
        conn = WorkspaceWSConnection(websocket, workspace_id)
        try:
            await conn.run(db_session=session)
        except WebSocketDisconnect:
            return
        except Exception:
            log.exception("ws_connection_error", workspace_id=str(workspace_id))
            return
