"""Shared async Redis client.

Used by:
  - Webhook dedupe (this turn) - keyed `seen_webhooks:<X-Webhook-ID>` set
  - Orchestrator session state (§C4)
  - Transcript bus (§C4 / §C5)

Per-event-loop singleton: each running asyncio loop gets its own Redis
client instance. This is required because redis-py's async client opens a
TCP transport bound to the loop that first issued a command on it; reusing
the same client from a different loop raises "Future attached to a
different loop". Test harnesses regularly create a Starlette TestClient
(which runs in its own anyio portal loop) alongside the pytest-asyncio
loop in the same test, so a process-wide singleton is unsafe.

`reset_redis_client()` clears every cached loop binding (used by tests
that want to rebind to a fake or a different URL).
"""

from __future__ import annotations

import asyncio
from typing import Protocol

import redis.asyncio as redis_async

from app.settings import get_settings


class RedisLike(Protocol):
    async def setnx(self, key: str, value: str) -> bool: ...
    async def expire(self, key: str, seconds: int) -> bool: ...
    async def exists(self, key: str) -> int: ...
    async def set(self, key: str, value: str, ex: int | None = None) -> bool | None: ...
    async def get(self, key: str) -> bytes | None: ...
    async def delete(self, *keys: str) -> int: ...
    async def aclose(self) -> None: ...


# Map id(loop) -> client. We key on id() rather than the loop object itself so
# garbage-collected loops don't keep their client alive via a strong ref.
_clients: dict[int, redis_async.Redis] = {}
# Explicit override (tests). When set, takes precedence over the per-loop map.
_override: redis_async.Redis | None = None


def _build_client() -> redis_async.Redis:
    settings = get_settings()
    return redis_async.from_url(
        settings.redis_url,
        socket_timeout=5,
        socket_connect_timeout=3,
        decode_responses=False,
    )


def get_redis() -> redis_async.Redis:
    """Return a Redis client bound to the current running event loop.

    Inside an async context the running loop pins the client; if called
    outside one (rare; defensive), fall back to a process-wide instance.
    """
    if _override is not None:
        return _override
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop; cache under a sentinel key so the fallback is
        # itself a singleton instead of leaking a fresh client per call.
        loop_key = 0
    else:
        loop_key = id(loop)
    client = _clients.get(loop_key)
    if client is None:
        client = _build_client()
        _clients[loop_key] = client
    return client


def set_redis_client(client: redis_async.Redis) -> None:
    """Override every loop-bound client with `client` (tests + fixtures)."""
    global _override
    _override = client


async def reset_redis_client() -> None:
    """Drop every cached client; close any prior connections best-effort."""
    global _override
    _override = None
    cached = list(_clients.values())
    _clients.clear()
    for c in cached:
        try:
            await c.aclose()
        except Exception:
            pass


# ---- Webhook dedupe helpers ----

WEBHOOK_DEDUPE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days per HLD §11.2.3


async def claim_webhook_id(delivery_id: str) -> bool:
    """Return True if this delivery_id is new; False if already seen.

    SET key value NX EX ttl is atomic - the first caller wins.
    """
    r = get_redis()
    key = f"seen_webhooks:{delivery_id}"
    result = await r.set(key, "1", nx=True, ex=WEBHOOK_DEDUPE_TTL_SECONDS)
    return bool(result)


# ---- WebSocket one-time tokens ----

WS_TOKEN_TTL_SECONDS = 30
WS_TOKEN_KEY_PREFIX = "ws_token:"


async def issue_ws_token(*, user_id: str, workspace_id: str) -> str:
    """Mint a short-lived token tied to (user_id, workspace_id).

    Browsers can't easily send Authorization headers on a WS upgrade, so the
    Manager POSTs to /workspaces/{wid}/ws/token with a normal access JWT and
    gets back this opaque value to pass in the ?token=... query string.
    """
    import secrets

    token = secrets.token_urlsafe(32)
    key = WS_TOKEN_KEY_PREFIX + token
    payload = f"{user_id}:{workspace_id}"
    r = get_redis()
    await r.set(key, payload, ex=WS_TOKEN_TTL_SECONDS)
    return token


async def claim_ws_token(token: str) -> tuple[str, str] | None:
    """Consume a token. Returns (user_id, workspace_id) or None if invalid/expired.

    GET-then-DEL ensures the token is single-use.
    """
    if not token:
        return None
    r = get_redis()
    key = WS_TOKEN_KEY_PREFIX + token
    raw = await r.get(key)
    if raw is None:
        return None
    await r.delete(key)
    payload = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    if ":" not in payload:
        return None
    user_id, workspace_id = payload.split(":", 1)
    return user_id, workspace_id
