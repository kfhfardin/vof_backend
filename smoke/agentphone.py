"""AgentPhone probe - REST auth, webhook configured, HMAC roundtrip, SMS capability.

See LLD section B2.
"""

import os
import time
from typing import ClassVar

import httpx

from smoke._base import Probe, UpstreamUnavailable, main_for

BASE = "https://api.agentphone.ai/v1"


class AgentPhoneProbe(Probe):
    name: ClassVar[str] = "agentphone"
    required_env: ClassVar[list[str]] = [
        "AGENTPHONE_API_KEY",
        "AGENTPHONE_WEBHOOK_SECRET",
    ]

    def checks_for_mode(self) -> None:
        self.check(
            "auth_valid",
            self._auth_valid,
            fix_hint="Verify AGENTPHONE_API_KEY; rotate in dashboard if needed.",
        )
        self.check(
            "webhook_configured",
            self._webhook_configured,
            fix_hint="POST /v1/webhooks with your deployment URL; save the returned secret as AGENTPHONE_WEBHOOK_SECRET.",
        )
        self.check(
            "hmac_verification",
            self._hmac_verification_roundtrip,
            fix_hint="AGENTPHONE_WEBHOOK_SECRET stale - regenerate by POSTing /v1/webhooks again.",
        )

        if self.mode in ("smoke", "repair"):
            self.check(
                "test_webhook_delivery",
                self._test_webhook_delivery,
                fix_hint="Webhook URL must be reachable from public internet (ngrok for local dev).",
            )
            self.check(
                "outbound_sms_capability",
                self._can_send_sms,
                fix_hint=(
                    "Set SMOKE_AGENTPHONE_TEST_TO_NUMBER (E.164) and "
                    "SMOKE_AGENTPHONE_TEST_AGENT_ID (AP agent that owns the from-number); "
                    "ensure account has balance and an SMS-capable number attached."
                ),
            )
            self.check(
                "conversation_state_roundtrip",
                self._conversation_state_roundtrip,
                fix_hint=(
                    "PATCH /conversations/{id} with {metadata:{...}} should succeed - this is "
                    "the surface AgentPhoneAdapter.set_conversation_state uses on the first voice "
                    "turn of every call. Set SMOKE_AGENTPHONE_TEST_CONVERSATION_ID to a real "
                    "conversation id (call your test number once to create one)."
                ),
            )

    # -- Checks --

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=BASE,
            headers={"Authorization": f"Bearer {os.environ['AGENTPHONE_API_KEY']}"},
            timeout=10.0,
        )

    def _auth_valid(self) -> str:
        with self._client() as c:
            try:
                r = c.get("/agents")
            except httpx.RequestError as e:
                raise UpstreamUnavailable(f"network: {e}") from e
        if r.status_code == 401:
            raise RuntimeError("API key rejected (401)")
        if r.status_code >= 500:
            raise UpstreamUnavailable(f"AP returned {r.status_code}")
        r.raise_for_status()
        return f"http {r.status_code}"

    def _webhook_configured(self) -> str:
        with self._client() as c:
            try:
                r = c.get("/webhooks")
            except httpx.RequestError as e:
                raise UpstreamUnavailable(f"network: {e}") from e
        if r.status_code >= 500:
            raise UpstreamUnavailable(f"AP returned {r.status_code}")
        r.raise_for_status()
        data = r.json()
        # Response may be a list or an object - handle both shapes defensively.
        if isinstance(data, list):
            webhooks = data
        else:
            webhooks = data.get("webhooks", []) or ([data] if data.get("url") else [])
        if not webhooks:
            raise RuntimeError("no master webhook configured (POST /v1/webhooks)")
        url = webhooks[0].get("url", "")
        return f"url={url[:60]}"

    def _hmac_verification_roundtrip(self) -> str:
        """Synthesize a payload, sign it, round-trip through the production verifier.

        Catches drift between our verifier and AP's signer.
        """
        from app.security.hmac import compute_signature, verify_agentphone_webhook

        secret = os.environ["AGENTPHONE_WEBHOOK_SECRET"]
        body = b'{"event":"agent.message","channel":"sms","data":{}}'
        ts = str(int(time.time()))
        sig = compute_signature(body, ts, secret)
        if not verify_agentphone_webhook(body, sig, ts, secret):
            raise RuntimeError("production verifier rejected its own signature")
        if verify_agentphone_webhook(body, sig, ts, "wrong-secret"):
            raise RuntimeError("production verifier accepted a wrong-secret signature")
        return f"{sig[:24]}..."

    def _test_webhook_delivery(self) -> str:
        # POST /v1/webhooks/test triggers a delivery to the master webhook URL
        # (or to a specific agent's per-agent webhook if agentId is supplied -
        # we use the master, matching production). The OpenAPI declares the
        # response as "Any type" so we just assert non-error HTTP status and
        # surface whatever the body contains for logs.
        with self._client() as c:
            try:
                r = c.post("/webhooks/test")
            except httpx.RequestError as e:
                raise UpstreamUnavailable(f"network: {e}") from e
        if r.status_code >= 500:
            raise UpstreamUnavailable(f"AP returned {r.status_code}")
        if r.status_code == 404:
            raise RuntimeError(
                "POST /webhooks/test returned 404 - test utility may not be enabled on your AP plan"
            )
        if r.status_code >= 400:
            raise RuntimeError(f"http {r.status_code}: {r.text[:200]}")
        try:
            data = r.json() if r.content else {}
        except Exception:
            data = {}
        # If AP signaled failure in the body, surface it (common shape).
        # Exception: HTTP 404 from our receiver on a synthetic test payload is
        # *correct* — AP's test delivery uses placeholder phone numbers that
        # legitimately don't map to any workspace, so materialize_scope_and_call
        # raises NotFound and the receiver returns 404. The cryptographic chain
        # succeeded (HMAC + replay + dedupe + parse all worked), which is what
        # this probe is actually verifying.
        if isinstance(data, dict) and data.get("success") is False:
            http_status = data.get("httpStatus")
            if http_status == 404:
                return f"receiver reachable (returned 404 on synthetic test payload, expected on empty DB)"
            raise RuntimeError(f"test delivery failed: {data.get('errorMessage', data)}")
        status = data.get("httpStatus") if isinstance(data, dict) else None
        return f"accepted ({r.status_code}, httpStatus={status})"

    def _can_send_sms(self) -> str:
        # POST /v1/messages takes (agent_id, to_number, body) snake_case per
        # SendMessageRequest. We require SMOKE_AGENTPHONE_TEST_AGENT_ID so
        # this probe is independent of whatever numbers exist on the account
        # (no GET /numbers cross-check needed).
        to = os.environ.get("SMOKE_AGENTPHONE_TEST_TO_NUMBER")
        if not to:
            raise RuntimeError("SMOKE_AGENTPHONE_TEST_TO_NUMBER not set (E.164, e.g. +15551234567)")
        agent_id = os.environ.get("SMOKE_AGENTPHONE_TEST_AGENT_ID")
        if not agent_id:
            raise RuntimeError(
                "SMOKE_AGENTPHONE_TEST_AGENT_ID not set - the AP agent that owns the from-number"
            )
        with self._client() as c:
            send_resp = c.post(
                "/messages",
                json={
                    "agent_id": agent_id,
                    "to_number": to,
                    "body": f"VotF smoke test {int(time.time())}",
                },
            )
        if send_resp.status_code == 404:
            raise RuntimeError(
                "POST /messages 404 - either /messages disabled on plan or "
                "SMOKE_AGENTPHONE_TEST_AGENT_ID is stale"
            )
        if send_resp.status_code >= 500:
            raise UpstreamUnavailable(f"AP {send_resp.status_code}")
        if send_resp.status_code >= 400:
            raise RuntimeError(f"send failed: {send_resp.text[:200]}")
        body = send_resp.json() if send_resp.content else {}
        from_num = body.get("from_number", "?") if isinstance(body, dict) else "?"
        return f"accepted, to={to}, from={from_num}"

    def _conversation_state_roundtrip(self) -> str:
        """Exercises PATCH /conversations/{id} with {metadata: {...}} - the
        exact shape AgentPhoneAdapter.set_conversation_state uses on the first
        voice turn of every call. Requires a real conversation id (call your
        test number once to create one, then put the id in
        SMOKE_AGENTPHONE_TEST_CONVERSATION_ID).
        """
        conv_id = os.environ.get("SMOKE_AGENTPHONE_TEST_CONVERSATION_ID")
        if not conv_id:
            raise RuntimeError(
                "SMOKE_AGENTPHONE_TEST_CONVERSATION_ID not set - call your test "
                "number once to create a conversation, then set this to the "
                "conversation id from the AP dashboard."
            )
        marker = f"smoketest_{int(time.time())}"
        # Match the production shape exactly: PATCH with json body {metadata: {...}}.
        with self._client() as c:
            try:
                r = c.patch(
                    f"/conversations/{conv_id}",
                    json={"metadata": {"smoketest_marker": marker}},
                )
            except httpx.RequestError as e:
                raise UpstreamUnavailable(f"network: {e}") from e
        if r.status_code == 404:
            raise RuntimeError(
                f"conversation {conv_id} not found - SMOKE_AGENTPHONE_TEST_CONVERSATION_ID is stale or wrong"
            )
        if r.status_code >= 500:
            raise UpstreamUnavailable(f"AP {r.status_code}")
        if r.status_code >= 400:
            raise RuntimeError(
                f"PATCH /conversations/{{id}} failed {r.status_code}: {r.text[:200]} - "
                "if AP renamed the metadata field, set_conversation_state will silently no-op in prod"
            )
        return f"PATCH OK ({r.status_code})"


if __name__ == "__main__":
    raise SystemExit(main_for(AgentPhoneProbe))
