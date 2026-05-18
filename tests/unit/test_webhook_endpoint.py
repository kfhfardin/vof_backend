"""Webhook endpoint - HMAC + replay + dedupe path (no DB needed for these)."""

import time

from app.security.hmac import compute_signature


async def test_missing_signature_returns_401(app_client) -> None:  # type: ignore[no-untyped-def]
    r = await app_client.post("/api/v1/webhooks/agentphone", content=b"{}")
    assert r.status_code == 401


async def test_bad_signature_returns_401(app_client) -> None:  # type: ignore[no-untyped-def]
    ts = str(int(time.time()))
    r = await app_client.post(
        "/api/v1/webhooks/agentphone",
        content=b'{"event":"agent.message"}',
        headers={
            "x-webhook-signature": "sha256=deadbeef",
            "x-webhook-timestamp": ts,
        },
    )
    assert r.status_code == 401


async def test_replay_window_exceeded_returns_400(app_client) -> None:  # type: ignore[no-untyped-def]
    body = b'{"event":"agent.message"}'
    old_ts = str(int(time.time()) - 1000)
    # Use the placeholder secret from conftest defaults; the secret value
    # doesn't matter here - the replay check fires before HMAC verify.
    sig = compute_signature(body, old_ts, "any-secret")
    r = await app_client.post(
        "/api/v1/webhooks/agentphone",
        content=body,
        headers={"x-webhook-signature": sig, "x-webhook-timestamp": old_ts},
    )
    assert r.status_code == 400
