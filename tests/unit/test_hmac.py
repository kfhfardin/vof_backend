"""AgentPhone HMAC verifier."""

import time

import pytest

from app.security.hmac import (
    ReplayWindowExceeded,
    compute_signature,
    verify_agentphone_webhook,
)


def test_signature_roundtrip() -> None:
    body = b'{"event":"agent.message"}'
    ts = str(int(time.time()))
    sig = compute_signature(body, ts, "secret")
    assert sig.startswith("sha256=")
    assert verify_agentphone_webhook(body, sig, ts, "secret")


def test_wrong_secret_rejected() -> None:
    body = b"x"
    ts = str(int(time.time()))
    sig = compute_signature(body, ts, "secret_a")
    assert not verify_agentphone_webhook(body, sig, ts, "secret_b")


def test_tampered_body_rejected() -> None:
    ts = str(int(time.time()))
    sig = compute_signature(b"original", ts, "secret")
    assert not verify_agentphone_webhook(b"tampered", sig, ts, "secret")


def test_replay_window_enforced() -> None:
    body = b"x"
    old_ts = str(int(time.time()) - 600)
    sig = compute_signature(body, old_ts, "secret")
    with pytest.raises(ReplayWindowExceeded):
        verify_agentphone_webhook(body, sig, old_ts, "secret")


def test_missing_headers_return_false() -> None:
    assert not verify_agentphone_webhook(b"x", "", "1234567890", "secret")
    assert not verify_agentphone_webhook(b"x", "sha256=abcd", "", "secret")


def test_malformed_timestamp_returns_false() -> None:
    assert not verify_agentphone_webhook(b"x", "sha256=abcd", "notanumber", "secret")
