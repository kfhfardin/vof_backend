"""Workspace-scoped frame bus over Redis pub/sub.

One channel per Workspace: `workspace:{wid}:frames`. Publishers (the
Orchestrator, the dispatcher, §C6 decisions) emit frames here; the
WS hub subscribes once per connection and forwards everything to the
client tagged with `call_id`.

Pub/sub is fire-and-forget: if no subscriber is connected, the frame is
dropped. That's fine for live view - the durable record is in
TranscriptFragment / DecisionRequest tables.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from app.logging import get_logger
from app.realtime.redis_client import get_redis

log = get_logger(__name__)


def workspace_frames_channel(workspace_id: UUID) -> str:
    return f"workspace:{workspace_id}:frames"


async def publish_frame(workspace_id: UUID, frame: dict[str, Any]) -> int:
    """Publish a frame to the Workspace's channel.

    Returns the number of subscribers that received it (0 = no live viewer).
    Fire-and-forget; failures are logged but don't propagate.
    """
    r = get_redis()
    try:
        return int(await r.publish(workspace_frames_channel(workspace_id), json.dumps(frame)))
    except Exception:
        log.exception("publish_frame_failed", workspace_id=str(workspace_id), type=frame.get("type"))
        return 0


@asynccontextmanager
async def subscribe_workspace_frames(
    workspace_id: UUID,
) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
    """Async-context-managed subscription to a Workspace's frame stream.

    Usage:
        async with subscribe_workspace_frames(wid) as frames:
            async for frame in frames:
                ...
    """
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(workspace_frames_channel(workspace_id))

    async def _iter() -> AsyncIterator[dict[str, Any]]:
        try:
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg is None:
                    # Cooperate with cancellation between polls
                    await asyncio.sleep(0)
                    continue
                if msg.get("type") != "message":
                    continue
                raw = msg["data"]
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    log.warning("bus_malformed_frame", workspace_id=str(workspace_id))
                    continue
        finally:
            pass

    try:
        yield _iter()
    finally:
        try:
            await pubsub.unsubscribe(workspace_frames_channel(workspace_id))
        except Exception:
            pass
        try:
            await pubsub.aclose()
        except Exception:
            pass
