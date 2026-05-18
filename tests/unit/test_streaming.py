"""NDJSON streamer + bridge-chunk."""

import asyncio
import json
from collections.abc import AsyncIterator

from app.orchestrator.streaming import (
    emit_bridge_if_slow,
    hangup_chunk,
    token_stream_to_ndjson,
)


async def _tokens(parts: list[str]) -> AsyncIterator[str]:
    for p in parts:
        yield p


async def test_token_stream_emits_interim_and_final() -> None:
    chunks = []
    async for c in token_stream_to_ndjson(_tokens(["Hello ", "there ", "Sarah."]), chunk_chars=8):
        chunks.append(json.loads(c.decode().rstrip("\n")))
    # We have at least one interim (true) chunk and exactly one final (no interim key).
    interim_count = sum(1 for c in chunks if c.get("interim"))
    final_count = sum(1 for c in chunks if "interim" not in c)
    assert interim_count >= 1
    assert final_count == 1
    combined = "".join(c["text"] for c in chunks)
    assert combined.strip() == "Hello there Sarah."


async def test_token_stream_emits_empty_final_when_no_tokens() -> None:
    chunks = []
    async for c in token_stream_to_ndjson(_tokens([])):
        chunks.append(json.loads(c.decode().rstrip("\n")))
    assert chunks == [{"text": ""}]


async def test_bridge_is_emitted_when_work_is_slow() -> None:
    async def slow() -> str:
        await asyncio.sleep(0.5)
        return "done"

    result, bridge = await emit_bridge_if_slow(slow(), bridge_after_ms=50)
    assert result == "done"
    assert bridge is not None
    payload = json.loads(bridge.decode().rstrip("\n"))
    assert payload.get("interim") is True
    assert payload["text"]


async def test_bridge_skipped_when_work_is_fast() -> None:
    async def fast() -> str:
        return "instant"

    result, bridge = await emit_bridge_if_slow(fast(), bridge_after_ms=300)
    assert result == "instant"
    assert bridge is None


def test_hangup_chunk_shape() -> None:
    payload = json.loads(hangup_chunk("rep_ended").decode().rstrip("\n"))
    assert payload["hangup"] is True
    assert payload["reason"] == "rep_ended"
