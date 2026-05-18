"""LLMClient stream_chat - real OpenAI-compat SSE parse + FakeLLMClient shape +
BedrockMessagesClient body-shape contract."""

import pytest

from app.skills.llm_client import BedrockMessagesClient, FakeLLMClient, OpenAICompatClient


async def test_fake_streams_canned_chunks() -> None:
    fake = FakeLLMClient(stream_chunks=[["Hel", "lo ", "world."]])
    parts = []
    async for c in fake.stream_chat(model="m", messages=[{"role": "user", "content": "x"}]):
        parts.append(c)
    assert parts == ["Hel", "lo ", "world."]


async def test_fake_default_chunk_when_queue_empty() -> None:
    fake = FakeLLMClient()
    parts = [c async for c in fake.stream_chat(model="m", messages=[{"role": "user", "content": "x"}])]
    assert parts == ["ok."]


async def test_real_client_parses_sse_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    """Round-trip an SSE-shaped payload through the real client via httpx mock."""
    import httpx

    # SSE payload AP/OpenAI-compat emits during streaming.
    sse_body = (
        b'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"world"}}]}\n\n'
        b'data: {"choices":[{"delta":{}}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body, headers={"Content-Type": "text/event-stream"})

    transport = httpx.MockTransport(handler)

    client = OpenAICompatClient(base_url="http://example", api_key="k")

    # The cached client is built lazily by _get_client(). Pre-seed it with
    # an httpx.AsyncClient wired to the MockTransport so the production
    # code path uses the mocked response.
    client._client_inst = httpx.AsyncClient(
        base_url="http://example",
        transport=transport,
        headers={"Authorization": "Bearer k"},
        timeout=60.0,
    )

    parts: list[str] = []
    async for c in client.stream_chat(model="m", messages=[{"role": "user", "content": "x"}]):
        parts.append(c)
    assert parts == ["Hello ", "world"]
    await client.close()


# ---------------- BedrockMessagesClient — pure-function shape tests ----------------


def test_bedrock_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        BedrockMessagesClient(api_key="", region="us-east-1")


def test_bedrock_constructor_surfaces_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructor must put the API key into AWS_BEARER_TOKEN_BEDROCK so boto3
    picks it up — this is the load-bearing wiring that lets ANTHROPIC_API_KEY
    work end-to-end without IAM creds."""
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    BedrockMessagesClient(api_key="sk-bedrock-test", region="us-east-1")
    import os as _os

    assert _os.environ.get("AWS_BEARER_TOKEN_BEDROCK") == "sk-bedrock-test"


def test_bedrock_split_system_extracts_system_message() -> None:
    """Anthropic Messages API takes `system` as a top-level string, not as a
    role:system message. The client must hoist it out."""
    msgs = [
        {"role": "system", "content": "you are a test"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
    ]
    system, rest = BedrockMessagesClient._split_system(msgs)
    assert system == "you are a test"
    assert rest == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
    ]


def test_bedrock_split_system_concatenates_multiple_systems() -> None:
    msgs = [
        {"role": "system", "content": "rule one"},
        {"role": "user", "content": "hi"},
        {"role": "system", "content": "rule two"},
    ]
    system, rest = BedrockMessagesClient._split_system(msgs)
    assert system == "rule one\n\nrule two"
    assert rest == [{"role": "user", "content": "hi"}]


def test_bedrock_split_system_when_no_system() -> None:
    msgs = [{"role": "user", "content": "hi"}]
    system, rest = BedrockMessagesClient._split_system(msgs)
    assert system is None
    assert rest == msgs


def test_bedrock_body_pins_api_version_and_max_tokens() -> None:
    """The body sent to Bedrock invoke_model must declare
    anthropic_version=bedrock-2023-05-31 — without it Bedrock rejects the
    request."""
    import json as _json

    c = BedrockMessagesClient(api_key="k", region="us-east-1")
    _, body = c._body(messages=[{"role": "user", "content": "hi"}], max_tokens=42)
    payload = _json.loads(body)
    assert payload["anthropic_version"] == "bedrock-2023-05-31"
    assert payload["max_tokens"] == 42
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert "system" not in payload


def test_bedrock_body_includes_system_when_present() -> None:
    import json as _json

    c = BedrockMessagesClient(api_key="k", region="us-east-1")
    _, body = c._body(
        messages=[
            {"role": "system", "content": "you are a test"},
            {"role": "user", "content": "hi"},
        ],
        max_tokens=10,
    )
    payload = _json.loads(body)
    assert payload["system"] == "you are a test"
    assert payload["messages"] == [{"role": "user", "content": "hi"}]


def test_get_llm_client_returns_bedrock_when_provider_is_bedrock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider switch wires the right client. We invalidate the singleton
    by re-importing the module — the get_settings cache + the _client global
    are both module-level singletons."""
    import app.settings as settings_mod
    import app.skills.llm_client as llm_mod

    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-bedrock-singleton-test")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    settings_mod.get_settings.cache_clear()
    llm_mod._client = None
    try:
        client = llm_mod.get_llm_client()
        assert isinstance(client, BedrockMessagesClient)
    finally:
        llm_mod._client = None
        settings_mod.get_settings.cache_clear()


def test_get_llm_client_returns_openai_when_provider_is_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.settings as settings_mod
    import app.skills.llm_client as llm_mod

    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_API_KEY", "sk-openai-singleton-test")

    settings_mod.get_settings.cache_clear()
    llm_mod._client = None
    try:
        client = llm_mod.get_llm_client()
        assert isinstance(client, OpenAICompatClient)
    finally:
        llm_mod._client = None
        settings_mod.get_settings.cache_clear()


# ---------------- Client caching contract — every adapter ----------------
# These tests prove that long-lived adapters cache their underlying
# transport (httpx pool, aiobotocore client, SDK instance) instead of
# rebuilding it per call. Cache regressions are silent-but-expensive
# performance bugs — every TLS handshake adds 200–800ms (warm) and seconds
# (cold) to the hot path.


async def test_openai_compat_client_caches_httpx_across_calls() -> None:
    """Subsequent _get_client() calls must return the SAME httpx instance."""
    client = OpenAICompatClient(base_url="http://example", api_key="k")
    c1 = await client._get_client()
    c2 = await client._get_client()
    assert c1 is c2, "OpenAICompatClient must cache the httpx.AsyncClient"
    await client.close()
    assert client._client_inst is None, "close() must release the cached client"


async def test_bedrock_client_caches_aiobotocore_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """BedrockMessagesClient._get_client() must reuse one aiobotocore client.
    We stub aiobotocore to avoid hitting AWS."""
    import app.skills.llm_client as llm_mod

    class _FakeClientCM:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return object()

        async def __aexit__(self, *a):  # type: ignore[no-untyped-def]
            return False

    class _FakeSession:
        def create_client(self, *a, **k):  # type: ignore[no-untyped-def]
            return _FakeClientCM()

    class _FakeSessionMod:
        AioSession = _FakeSession

    import sys

    monkeypatch.setitem(sys.modules, "aiobotocore.session", _FakeSessionMod())
    bedrock = llm_mod.BedrockMessagesClient(api_key="k", region="us-east-1")
    c1 = await bedrock._get_client()
    c2 = await bedrock._get_client()
    assert c1 is c2, "BedrockMessagesClient must cache the aiobotocore client"
    await bedrock.close()
    assert bedrock._client is None


async def test_agentphone_adapter_caches_httpx_across_calls() -> None:
    """AgentPhoneAdapter._get_client() must reuse one httpx pool."""
    from app.telephony.agentphone import AgentPhoneAdapter

    adapter = AgentPhoneAdapter(api_key="ap_test")
    c1 = await adapter._get_client()
    c2 = await adapter._get_client()
    assert c1 is c2, "AgentPhoneAdapter must cache the httpx.AsyncClient"
    await adapter.close()
    assert adapter._client_inst is None


async def test_supermemory_provider_caches_sdk_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """SupermemoryCallerMemoryProvider._get_client() must reuse one SDK client."""
    import app.memory.supermemory as sm_mod

    class _FakeSDK:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(sm_mod, "_build_async_client", lambda key: _FakeSDK(key))

    provider = sm_mod.SupermemoryCallerMemoryProvider(api_key="sm_test")
    c1 = await provider._get_client()
    c2 = await provider._get_client()
    assert c1 is c2, "SupermemoryCallerMemoryProvider must cache the AsyncSupermemory client"
    await provider.close()
    assert provider._client_inst is None


async def test_s3_object_store_caches_aiobotocore_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """S3ObjectStore._get_client() must reuse one aiobotocore client."""
    import app.storage.s3 as s3_mod

    class _FakeClient:
        async def put_object(self, **k):  # type: ignore[no-untyped-def]
            return {}

    class _FakeClientCM:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return _FakeClient()

        async def __aexit__(self, *a):  # type: ignore[no-untyped-def]
            return False

    class _FakeSession:
        def create_client(self, *a, **k):  # type: ignore[no-untyped-def]
            return _FakeClientCM()

    monkeypatch.setattr(s3_mod, "get_session", lambda: _FakeSession())

    store = s3_mod.S3ObjectStore()
    c1 = await store._get_client()
    c2 = await store._get_client()
    assert c1 is c2, "S3ObjectStore must cache the aiobotocore client"
    await store.close()
    assert store._client is None
