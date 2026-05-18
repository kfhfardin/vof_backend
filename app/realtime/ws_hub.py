"""WebSocket connection hub.

One `WorkspaceWSConnection` per connected client. Steps:

  1. Accept the upgrade.
  2. Build + send the initial Snapshot frame (in-progress calls).
  3. Spin a background heartbeat task (ping every 20s).
  4. Subscribe to the Workspace's bus channel.
  5. Forward every frame received from the bus to the client (JSON).
  6. On client disconnect or upstream error, cancel everything and close.

The hub is intentionally thin: it doesn't filter, it doesn't transform.
Publishers are responsible for emitting workspace-scoped frames.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.db.repositories.calls_repo import CallsRepo
from app.logging import get_logger
from app.realtime.bus import subscribe_workspace_frames
from app.schemas.ws_frames import CallStartedFrame, PingFrame, SnapshotFrame

log = get_logger(__name__)

HEARTBEAT_INTERVAL_S = 20
SEND_BUFFER_MAX = 100  # drop after N pending sends per slow client


async def _build_snapshot(session: AsyncSession, workspace_id: UUID) -> SnapshotFrame:
    repo = CallsRepo(session)
    in_progress = await repo.list_in_progress(workspace_id)
    return SnapshotFrame(
        calls=[
            CallStartedFrame(
                call_id=c.id,
                field_employee_id=c.field_employee_id,
                started_at=c.started_at,
            )
            for c in in_progress
        ]
    )


class WorkspaceWSConnection:
    def __init__(self, ws: WebSocket, workspace_id: UUID) -> None:
        self._ws = ws
        self._workspace_id = workspace_id
        self._send_buffer: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SEND_BUFFER_MAX)
        self._closed = False
        self._dropped = 0

    async def run(self, *, db_session: AsyncSession) -> None:
        await self._ws.accept()
        # Send initial snapshot before anything else so the FE renders the
        # in-progress calls without a separate REST roundtrip.
        snapshot = await _build_snapshot(db_session, self._workspace_id)
        await self._direct_send(snapshot.model_dump(mode="json"))

        sender_task = asyncio.create_task(self._sender_loop())
        receiver_task = asyncio.create_task(self._receiver_loop())
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        bus_task = asyncio.create_task(self._bus_loop())

        try:
            done, pending = await asyncio.wait(
                {sender_task, receiver_task, heartbeat_task, bus_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            for t in pending:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
            # Surface any task error for logging
            for t in done:
                exc = t.exception() if not t.cancelled() else None
                if exc and not isinstance(exc, WebSocketDisconnect):
                    log.exception(
                        "ws_task_failed",
                        workspace_id=str(self._workspace_id),
                        task=t.get_name(),
                        exc_info=exc,
                    )
        finally:
            self._closed = True
            try:
                await self._ws.close()
            except Exception:
                pass
            if self._dropped:
                log.warning(
                    "ws_frames_dropped",
                    workspace_id=str(self._workspace_id),
                    dropped=self._dropped,
                )

    # ---- Loops ----

    async def _bus_loop(self) -> None:
        async with subscribe_workspace_frames(self._workspace_id) as frames:
            async for frame in frames:
                if self._closed:
                    return
                try:
                    self._send_buffer.put_nowait(frame)
                except asyncio.QueueFull:
                    self._dropped += 1

    async def _sender_loop(self) -> None:
        try:
            while not self._closed:
                frame = await self._send_buffer.get()
                await self._direct_send(frame)
        except WebSocketDisconnect:
            return

    async def _receiver_loop(self) -> None:
        # We don't expect client-originated messages yet; receiving lets us
        # detect a client-initiated disconnect promptly.
        try:
            while True:
                await self._ws.receive_text()
        except WebSocketDisconnect:
            return

    async def _heartbeat_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            ping = PingFrame(ts=datetime.now(UTC))
            try:
                self._send_buffer.put_nowait(ping.model_dump(mode="json"))
            except asyncio.QueueFull:
                self._dropped += 1

    async def _direct_send(self, payload: dict[str, Any]) -> None:
        try:
            await self._ws.send_text(json.dumps(payload, default=str))
        except WebSocketDisconnect:
            raise
        except Exception:
            log.exception("ws_send_failed", workspace_id=str(self._workspace_id))
            raise
