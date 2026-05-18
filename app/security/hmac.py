"""HMAC verification for incoming provider webhooks.

The AgentPhone scheme (per HLD §5.1 / §11.2.3 / LLD §C3):
    signed_payload = timestamp + "." + raw_body
    expected = HMAC-SHA256(secret, signed_payload).hex()
    header   = "sha256=" + expected

Verification must use constant-time comparison and reject deliveries older
than 5 minutes (replay window).

This function is exercised by the smoke probe (smoke.agentphone.hmac_verification
- which catches algorithm drift between our verifier and AP's signer).
"""

import hashlib
import hmac as _hmac
import time

REPLAY_WINDOW_SECONDS = 300


class BadSignature(Exception):
    pass


class ReplayWindowExceeded(Exception):
    pass


def compute_signature(raw_body: bytes, timestamp: str, secret: str) -> str:
    """Compute the expected `sha256=...` signature header value."""
    signed = f"{timestamp}.".encode() + raw_body
    digest = _hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_agentphone_webhook(
    raw_body: bytes,
    signature_header: str,
    timestamp_header: str,
    secret: str,
    *,
    now: float | None = None,
    window_seconds: int = REPLAY_WINDOW_SECONDS,
) -> bool:
    """Return True iff signature + timestamp pass; raise on hard failures.

    Hard failures:
      - timestamp is outside the replay window -> ReplayWindowExceeded
    Soft failures (return False):
      - signature mismatch
      - malformed header
    """
    if not signature_header or not timestamp_header:
        return False

    # Replay window
    try:
        ts = int(timestamp_header)
    except ValueError:
        return False
    current = now if now is not None else time.time()
    if abs(current - ts) > window_seconds:
        raise ReplayWindowExceeded(f"timestamp {ts} outside {window_seconds}s window")

    expected = compute_signature(raw_body, timestamp_header, secret)
    return _hmac.compare_digest(expected, signature_header)
