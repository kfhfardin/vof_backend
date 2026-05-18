"""LLM probe.

Two provider modes selected by LLM_PROVIDER:
  - openai_compat (default): hits LLM_BASE_URL/chat/completions with the
    OpenAI shape; works against Anthropic /v1/openai, OpenAI itself, LiteLLM
    proxies, etc.
  - bedrock: hits AWS Bedrock invoke_model + invoke_model_with_response_stream
    using the native Anthropic Messages API body. Required when production
    code uses BedrockMessagesClient.

In bedrock mode:
  - ANTHROPIC_API_KEY holds the Bedrock long-term API key (surfaced to boto3
    as AWS_BEARER_TOKEN_BEDROCK)
  - AWS_REGION sets the runtime endpoint region
  - LLM_MODEL must be a cross-region inference profile id, e.g.
    `us.anthropic.claude-sonnet-4-6`. Plain Anthropic IDs raise
    ValidationException ("on-demand throughput isn't supported - retry with
    an inference profile").

See LLD section B4.
"""

import json
import os
import time
from typing import ClassVar

import httpx

from smoke._base import Probe, UpstreamUnavailable, main_for


def _provider() -> str:
    return (os.environ.get("LLM_PROVIDER") or "openai_compat").lower()


def _bedrock_required() -> list[str]:
    return ["ANTHROPIC_API_KEY", "AWS_REGION", "LLM_MODEL"]


def _openai_required() -> list[str]:
    return ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"]


class LLMProbe(Probe):
    name: ClassVar[str] = "llm"
    required_env: ClassVar[list[str]] = _openai_required()

    def checks_for_mode(self) -> None:
        # Resolve required_env per provider before any checks run.
        type(self).required_env = (
            _bedrock_required() if _provider() == "bedrock" else _openai_required()
        )
        provider = _provider()
        is_bedrock = provider == "bedrock"

        self.check(
            "auth_valid",
            self._auth_valid_bedrock if is_bedrock else self._auth_valid,
            fix_hint=(
                "Bedrock: verify ANTHROPIC_API_KEY (the long-term Bedrock API key) and AWS_REGION."
                if is_bedrock
                else "Verify LLM_API_KEY and LLM_BASE_URL match the provider."
            ),
        )
        self.check(
            "basic_completion",
            self._basic_completion_bedrock if is_bedrock else self._basic_completion,
            fix_hint=(
                "Bedrock: LLM_MODEL must be a cross-region inference profile id "
                "(e.g. us.anthropic.claude-sonnet-4-6). 'on-demand throughput' errors "
                "mean you passed a non-profile id."
                if is_bedrock
                else "Check LLM_MODEL; some models require account-level enablement."
            ),
        )

        if self.mode in ("smoke", "repair"):
            self.check(
                "streaming_completion",
                self._streaming_bedrock if is_bedrock else self._streaming_completion,
                fix_hint="Hot path requires streaming. Bedrock uses invoke_model_with_response_stream; OpenAI-compat uses SSE.",
            )
            self.check(
                "json_mode",
                self._json_mode_bedrock if is_bedrock else self._json_mode,
                fix_hint=(
                    "Bedrock: the Anthropic Messages API has no response_format switch; "
                    "we rely on prompt-level JSON instructions and strip any markdown fencing. "
                    "Failure here means the model emitted prose despite the instruction."
                    if is_bedrock
                    else "Classifier skill requires response_format=json_object."
                ),
            )
            self.check(
                "tool_calls",
                self._tool_calls_bedrock if is_bedrock else self._tool_calls,
                fix_hint="Orchestrator tools require function/tool-calling support.",
            )

    # -- OpenAI-compat checks (existing) --

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=os.environ["LLM_BASE_URL"].rstrip("/"),
            headers={
                "Authorization": f"Bearer {os.environ['LLM_API_KEY']}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def _post(self, path: str, body: dict) -> httpx.Response:  # type: ignore[type-arg]
        with self._client() as c:
            try:
                return c.post(path, json=body)
            except httpx.RequestError as e:
                raise UpstreamUnavailable(f"network: {e}") from e

    def _auth_valid(self) -> str:
        r = self._post(
            "/chat/completions",
            {
                "model": os.environ["LLM_MODEL"],
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            },
        )
        if r.status_code == 401:
            raise RuntimeError("API key rejected (401)")
        if r.status_code == 402:
            raise RuntimeError("payment required - add a payment method to the provider account")
        if r.status_code >= 500:
            raise UpstreamUnavailable(f"provider {r.status_code}")
        if r.status_code >= 400:
            raise RuntimeError(f"http {r.status_code}: {r.text[:200]}")
        return f"model={os.environ['LLM_MODEL']}"

    def _basic_completion(self) -> str:
        r = self._post(
            "/chat/completions",
            {
                "model": os.environ["LLM_MODEL"],
                "messages": [{"role": "user", "content": "Reply with exactly one word: pong"}],
                "max_tokens": 8,
            },
        )
        if r.status_code >= 500:
            raise UpstreamUnavailable(f"provider {r.status_code}")
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        if "pong" not in content.lower():
            raise RuntimeError(f"unexpected reply: {content!r}")
        return f"reply={content.strip()!r}"

    def _streaming_completion(self) -> str:
        first_token_ms: float | None = None
        t0 = time.time()
        body = {
            "model": os.environ["LLM_MODEL"],
            "messages": [{"role": "user", "content": "Count 1 to 5."}],
            "stream": True,
            "max_tokens": 50,
        }
        with self._client() as c:
            try:
                with c.stream("POST", "/chat/completions", json=body) as r:
                    if r.status_code >= 500:
                        raise UpstreamUnavailable(f"provider {r.status_code}")
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if not line:
                            continue
                        if line.startswith("data: ") and "[DONE]" not in line:
                            if first_token_ms is None:
                                first_token_ms = (time.time() - t0) * 1000
            except httpx.RequestError as e:
                raise UpstreamUnavailable(f"network: {e}") from e
        if first_token_ms is None:
            raise RuntimeError("no streamed tokens received")
        return f"first_token={first_token_ms:.0f}ms"

    def _json_mode(self) -> str:
        r = self._post(
            "/chat/completions",
            {
                "model": os.environ["LLM_MODEL"],
                "messages": [
                    {
                        "role": "user",
                        "content": 'Reply with ONLY this JSON, nothing else: {"status":"ok"}',
                    }
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 50,
            },
        )
        if r.status_code >= 500:
            raise UpstreamUnavailable(f"provider {r.status_code}")
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if parsed.get("status") != "ok":
            raise RuntimeError(f"unexpected JSON: {parsed!r}")
        return "json shape honored"

    def _tool_calls(self) -> str:
        r = self._post(
            "/chat/completions",
            {
                "model": os.environ["LLM_MODEL"],
                "messages": [{"role": "user", "content": "What's the weather in San Francisco right now?"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "description": "Get current weather for a city",
                            "parameters": {
                                "type": "object",
                                "properties": {"location": {"type": "string"}},
                                "required": ["location"],
                            },
                        },
                    }
                ],
                "tool_choice": "auto",
                "max_tokens": 200,
            },
        )
        if r.status_code >= 500:
            raise UpstreamUnavailable(f"provider {r.status_code}")
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            raise RuntimeError(f"model did not invoke a tool; content={msg.get('content')!r}")
        return f"tool_call={calls[0]['function']['name']}"

    # -- Bedrock invoke_model checks --

    def _bedrock_client(self):  # type: ignore[no-untyped-def]
        import boto3

        # Surface ANTHROPIC_API_KEY (the Bedrock long-term API key) as the
        # AWS bearer token so boto3 picks it up at client construction.
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = os.environ["ANTHROPIC_API_KEY"]
        return boto3.client("bedrock-runtime", region_name=os.environ["AWS_REGION"])

    def _bedrock_body(self, *, messages: list[dict[str, str]], max_tokens: int) -> str:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": messages,
            "max_tokens": max_tokens,
        }
        return json.dumps(body)

    def _bedrock_invoke(self, *, messages: list[dict[str, str]], max_tokens: int) -> dict:  # type: ignore[type-arg]
        client = self._bedrock_client()
        try:
            response = client.invoke_model(
                modelId=os.environ["LLM_MODEL"],
                body=self._bedrock_body(messages=messages, max_tokens=max_tokens),
            )
        except Exception as e:
            self._raise_bedrock(e)
        payload = response["body"].read()
        return json.loads(payload)

    @staticmethod
    def _raise_bedrock(e: Exception) -> None:
        msg = str(e)
        name = type(e).__name__
        if "AccessDenied" in name or "Unauthorized" in name or "ExpiredToken" in name:
            raise RuntimeError(f"auth rejected: {msg[:200]}") from e
        if "Validation" in name and "inference profile" in msg.lower():
            raise RuntimeError(
                f"model id requires cross-region inference profile (use us.anthropic...): {msg[:200]}"
            ) from e
        if "Throttling" in name or "TooManyRequests" in name or "ServiceUnavailable" in name:
            raise UpstreamUnavailable(f"{name}: {msg[:200]}") from e
        raise RuntimeError(f"{name}: {msg[:200]}") from e

    def _auth_valid_bedrock(self) -> str:
        out = self._bedrock_invoke(
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=4,
        )
        return f"model={os.environ['LLM_MODEL']}  stop={out.get('stop_reason', '?')}"

    def _basic_completion_bedrock(self) -> str:
        out = self._bedrock_invoke(
            messages=[{"role": "user", "content": "Reply with exactly one word: pong"}],
            max_tokens=16,
        )
        text = "".join(b.get("text", "") for b in out.get("content", []) if isinstance(b, dict))
        if "pong" not in text.lower():
            raise RuntimeError(f"unexpected reply: {text!r}")
        return f"reply={text.strip()!r}"

    def _streaming_bedrock(self) -> str:
        first_token_ms: float | None = None
        t0 = time.time()
        client = self._bedrock_client()
        try:
            response = client.invoke_model_with_response_stream(
                modelId=os.environ["LLM_MODEL"],
                body=self._bedrock_body(
                    messages=[{"role": "user", "content": "Count 1 to 5."}],
                    max_tokens=50,
                ),
            )
        except Exception as e:
            self._raise_bedrock(e)
        for event in response["body"]:
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
            if payload.get("type") == "content_block_delta":
                text = (payload.get("delta") or {}).get("text")
                if text and first_token_ms is None:
                    first_token_ms = (time.time() - t0) * 1000
        if first_token_ms is None:
            raise RuntimeError("no streamed tokens received")
        return f"first_token={first_token_ms:.0f}ms"

    def _json_mode_bedrock(self) -> str:
        # Anthropic Messages API has no response_format switch; rely on the
        # prompt and strip any markdown fencing (mirrors BedrockMessagesClient).
        out = self._bedrock_invoke(
            messages=[
                {
                    "role": "user",
                    "content": (
                        'Reply with ONLY this JSON object, no prose, no markdown: {"status":"ok"}'
                    ),
                }
            ],
            max_tokens=50,
        )
        text = "".join(b.get("text", "") for b in out.get("content", []) if isinstance(b, dict))
        t = text.strip()
        if t.startswith("```"):
            t = t.strip("`")
            if t.startswith("json"):
                t = t[4:]
        try:
            parsed = json.loads(t.strip())
        except json.JSONDecodeError as e:
            raise RuntimeError(f"model returned non-JSON: {text[:120]!r}") from e
        if parsed.get("status") != "ok":
            raise RuntimeError(f"unexpected JSON: {parsed!r}")
        return "json shape honored (prompt-level)"

    def _tool_calls_bedrock(self) -> str:
        # Anthropic Messages tool format (different field names from OpenAI's).
        client = self._bedrock_client()
        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "messages": [
                    {
                        "role": "user",
                        "content": "What's the weather in San Francisco right now?",
                    }
                ],
                "tools": [
                    {
                        "name": "get_weather",
                        "description": "Get current weather for a city",
                        "input_schema": {
                            "type": "object",
                            "properties": {"location": {"type": "string"}},
                            "required": ["location"],
                        },
                    }
                ],
                "max_tokens": 200,
            }
        )
        try:
            response = client.invoke_model(modelId=os.environ["LLM_MODEL"], body=body)
        except Exception as e:
            self._raise_bedrock(e)
        out = json.loads(response["body"].read())
        for block in out.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                return f"tool_call={block.get('name')}"
        raise RuntimeError(f"model did not invoke a tool; content={out.get('content')!r}")


if __name__ == "__main__":
    raise SystemExit(main_for(LLMProbe))
