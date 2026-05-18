"""LLM client abstraction.

Production: two providers selected by LLM_PROVIDER:
  - openai_compat (default) — any OpenAI-compatible endpoint. Auth via
    LLM_API_KEY bearer; base URL from LLM_BASE_URL.
  - bedrock — AWS Bedrock invoke_model + invoke_model_with_response_stream
    using the native Anthropic Messages API body. Auth via the Bedrock
    long-term API key (stored in ANTHROPIC_API_KEY); surfaced to boto3 as
    AWS_BEARER_TOKEN_BEDROCK at client construction. Model IDs must be
    Bedrock-format cross-region inference profiles (e.g.
    `us.anthropic.claude-sonnet-4-6`).

Tests: a deterministic fake injected via set_llm_client().

Two surface methods:
  - complete_json: skill path (LLMSkill - one shot, validated against schema)
  - stream_chat:   orchestrator hot path (yields token-group strings as they arrive)
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Protocol

import httpx

from app.settings import get_settings


class LLMClient(Protocol):
    async def complete_json(self, *, model: str, messages: list[dict[str, str]]) -> str:
        """Return the model's response as a JSON string."""

    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 1500,
    ) -> AsyncIterator[str]:
        """Stream the assistant's text response in token-group chunks.

        Implementations may yield small text fragments. The Orchestrator wraps
        each chunk in an NDJSON envelope before sending it to AgentPhone (§C4).
        """


class OpenAICompatClient:
    """OpenAI-compatible chat-completions client.

    The httpx.AsyncClient is created **once per provider instance** and
    reused for every call. Each fresh client costs a TLS handshake + auth
    setup (~200-800ms warm, multiple seconds cold), so the previous pattern
    of opening a new client per request added that cost to every skill call
    and every orchestrator voice turn. Lifespan shutdown calls close() to
    drain the connection pool gracefully.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client_inst: httpx.AsyncClient | None = None
        self._init_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client_inst is not None:
            return self._client_inst
        async with self._init_lock:
            if self._client_inst is not None:
                return self._client_inst
            self._client_inst = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                # Per-request timeouts on the call sites override this default.
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        return self._client_inst

    async def close(self) -> None:
        """Drain the connection pool. Called from FastAPI lifespan shutdown."""
        if self._client_inst is not None:
            await self._client_inst.aclose()
            self._client_inst = None

    async def complete_json(self, *, model: str, messages: list[dict[str, str]]) -> str:
        body = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_tokens": 2000,
        }
        c = await self._get_client()
        r = await c.post("/chat/completions", json=body, timeout=30.0)
        r.raise_for_status()
        data = r.json()
        content: str = data["choices"][0]["message"]["content"]
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:]
        return stripped.strip()

    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 1500,
    ) -> AsyncIterator[str]:
        return self._stream(model=model, messages=messages, max_tokens=max_tokens)

    async def _stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> AsyncIterator[str]:
        body = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
        }
        c = await self._get_client()
        async with c.stream("POST", "/chat/completions", json=body, timeout=60.0) as r:
            r.raise_for_status()
            async for raw in r.aiter_lines():
                if not raw:
                    continue
                line = raw.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if payload == "[DONE]":
                    return
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                chunk = delta.get("content")
                if chunk:
                    yield chunk


class BedrockMessagesClient:
    """AWS Bedrock invoke_model client using the native Anthropic Messages API.

    Why not the OpenAI-compat path? AWS publishes both an OpenAI-compat
    endpoint and the native invoke_model API, but on many accounts the
    OpenAI-compat path returns 404 / UnknownOperationException — the native
    invoke_model is the universally-available surface.

    Auth: the Bedrock long-term API key (stored in ANTHROPIC_API_KEY in this
    deployment) is surfaced to boto3 via the AWS_BEARER_TOKEN_BEDROCK env
    var, which boto3 ≥ 1.34.103 reads automatically. No AWS IAM access key /
    secret are needed.

    Model IDs must be Bedrock cross-region inference profile IDs (e.g.
    `us.anthropic.claude-sonnet-4-6`). Plain Anthropic IDs like
    `anthropic.claude-sonnet-4-6` raise ValidationException ("on-demand
    throughput isn't supported - retry with an inference profile").
    """

    _ANTHROPIC_BEDROCK_API_VERSION = "bedrock-2023-05-31"

    def __init__(self, *, api_key: str, region: str) -> None:
        if not api_key:
            raise ValueError("BedrockMessagesClient requires a non-empty API key")
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = api_key
        self._region = region
        # Lazy-init aiobotocore client + session, reused across calls.
        # Creating a fresh client per call costs ~12s in TLS handshake +
        # auth dance vs ~800ms on a reused client (measured).
        # The client is kept open for the process lifetime; FastAPI lifespan
        # closes it on shutdown via close().
        self._session: object | None = None
        self._client: object | None = None
        self._client_cm: object | None = None
        self._init_lock = asyncio.Lock()

    async def _get_client(self):  # type: ignore[no-untyped-def]
        if self._client is not None:
            return self._client
        async with self._init_lock:
            if self._client is not None:
                return self._client
            from aiobotocore.session import AioSession

            self._session = AioSession()
            self._client_cm = self._session.create_client(  # type: ignore[union-attr]
                "bedrock-runtime", region_name=self._region
            )
            self._client = await self._client_cm.__aenter__()
        return self._client

    async def close(self) -> None:
        """Tear down the singleton client (call from FastAPI lifespan shutdown)."""
        if self._client_cm is not None:
            await self._client_cm.__aexit__(None, None, None)
            self._client_cm = None
            self._client = None
            self._session = None

    @staticmethod
    def _split_system(
        messages: list[dict[str, str]],
    ) -> tuple[str | None, list[dict[str, str]]]:
        """Anthropic Messages takes `system` as a top-level string,
        not as a `role: system` message. Split it out."""
        system: str | None = None
        rest: list[dict[str, str]] = []
        for m in messages:
            if m.get("role") == "system":
                system = (system + "\n\n" + m["content"]) if system else m["content"]
            else:
                rest.append(m)
        return system, rest

    def _body(
        self, *, messages: list[dict[str, str]], max_tokens: int
    ) -> tuple[str | None, str]:
        system, rest = self._split_system(messages)
        body: dict[str, object] = {
            "anthropic_version": self._ANTHROPIC_BEDROCK_API_VERSION,
            "messages": rest,
            "max_tokens": max_tokens,
        }
        if system is not None:
            body["system"] = system
        return system, json.dumps(body)

    async def complete_json(self, *, model: str, messages: list[dict[str, str]]) -> str:
        _, body = self._body(messages=messages, max_tokens=2000)
        client = await self._get_client()
        response = await client.invoke_model(modelId=model, body=body)
        payload = await response["body"].read()
        out = json.loads(payload)
        text = "".join(block.get("text", "") for block in out.get("content", []) if isinstance(block, dict))
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:]
        return stripped.strip()

    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 1500,
    ) -> AsyncIterator[str]:
        return self._stream(model=model, messages=messages, max_tokens=max_tokens)

    async def _stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> AsyncIterator[str]:
        _, body = self._body(messages=messages, max_tokens=max_tokens)
        client = await self._get_client()
        response = await client.invoke_model_with_response_stream(
            modelId=model, body=body
        )
        # EventStream is async-iterable. Each event has a "chunk" with bytes
        # containing one Anthropic stream event JSON.
        async for event in response["body"]:
            chunk = event.get("chunk")
            if not chunk:
                continue
            data = chunk.get("bytes")
            if not data:
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            kind = payload.get("type")
            if kind == "content_block_delta":
                delta = payload.get("delta") or {}
                text = delta.get("text")
                if text:
                    yield text
            elif kind == "message_stop":
                return


class FakeLLMClient:
    """For tests + dev when no API key is set.

    `responses` queues canned JSON strings for complete_json calls.
    `stream_chunks` queues lists of token-group strings for stream_chat calls.
    If a queue is empty when called, falls back to an echo of the user message
    (json path) or a single "ok" chunk (stream path).
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        stream_chunks: list[list[str]] | None = None,
    ) -> None:
        self.responses: list[str] = list(responses) if responses else []
        self.stream_chunks: list[list[str]] = list(stream_chunks) if stream_chunks else []
        self.calls: list[dict[str, object]] = []
        self.stream_calls: list[dict[str, object]] = []

    async def complete_json(self, *, model: str, messages: list[dict[str, str]]) -> str:
        self.calls.append({"model": model, "messages": messages})
        if not self.responses:
            user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
            return json.dumps({"echo": user_msg[:200]})
        return self.responses.pop(0)

    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 1500,
    ) -> AsyncIterator[str]:
        return self._fake_stream(model=model, messages=messages)

    async def _fake_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        self.stream_calls.append({"model": model, "messages": messages})
        chunks = self.stream_chunks.pop(0) if self.stream_chunks else ["ok."]
        for c in chunks:
            yield c


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Return the singleton client per LLM_PROVIDER.

    - openai_compat → OpenAICompatClient (LLM_API_KEY required)
    - bedrock       → BedrockMessagesClient (ANTHROPIC_API_KEY required;
                       holds the Bedrock long-term API key)

    Falls back to FakeLLMClient when the required key is empty; logs a
    warning + prints to stderr so dev environments don't silently produce
    garbage skill output.
    """
    global _client
    if _client is None:
        settings = get_settings()
        if settings.llm_provider == "bedrock":
            key = settings.anthropic_api_key.get_secret_value()
            if not key:
                _client = _fake_with_warning(
                    "ANTHROPIC_API_KEY",
                    "LLM_PROVIDER=bedrock requires ANTHROPIC_API_KEY (the Bedrock long-term API key)",
                )
            else:
                _client = BedrockMessagesClient(api_key=key, region=settings.aws_region)
        else:
            key = settings.llm_api_key.get_secret_value()
            if not key:
                _client = _fake_with_warning(
                    "LLM_API_KEY",
                    "LLM_PROVIDER=openai_compat requires LLM_API_KEY",
                )
            else:
                _client = OpenAICompatClient(base_url=str(settings.llm_base_url), api_key=key)
    return _client


def _fake_with_warning(var_name: str, detail: str) -> FakeLLMClient:
    import sys

    from app.logging import get_logger

    get_logger(__name__).warning(
        "llm_client_fallback_to_fake",
        detail=f"{var_name} is empty - skills will produce non-conforming output",
    )
    sys.stderr.write(
        f"WARNING: {detail}; using FakeLLMClient. Skills will not produce real "
        f"output. Set {var_name} in .env.local or call set_llm_client() in tests.\n"
    )
    return FakeLLMClient()


def set_llm_client(client: LLMClient) -> None:
    """Override the singleton (tests + fixtures)."""
    global _client
    _client = client
