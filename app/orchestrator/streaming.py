"""NDJSON streamer + bridge-chunk pattern.

AgentPhone's voice webhook expects a streamed NDJSON response:

    {"text": "Let me check on that...", "interim": true}\\n
    {"text": "Here's what I see..."}\\n

Two patterns implemented here:

  1. token_stream_to_ndjson: pass-through wrapper. Takes an async iterator
     of token-group strings (from LLMClient.stream_chat), accumulates them
     into NDJSON chunks (interim=True), then emits one final chunk with
     interim absent.

  2. emit_bridge_if_slow: races a long-running coroutine against a deadline.
     If the deadline hits first, yields a bridge chunk before the work
     finishes - keeps the caller from hearing silence (HLD §5.5.1).

The voice handler composes both: bridge-chunk before retrieval, then stream
the LLM tokens.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator, Awaitable

BRIDGE_PHRASES = [
    "Let me check on that...",
    "Give me a sec...",
    "One moment...",
    "Hold on, looking that up...",
]


def _ndjson(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload) + "\n").encode("utf-8")


async def emit_bridge_if_slow[T](
    work: Awaitable[T],
    *,
    bridge_after_ms: int = 300,
) -> tuple[T, bytes | None]:
    """Run `work`. If it doesn't complete within `bridge_after_ms`, return a
    bridge NDJSON chunk alongside the eventual result.

    Returns (result, bridge_chunk_or_None). The caller decides whether to
    yield the bridge before yielding LLM chunks.
    """

    async def _run() -> T:
        return await work

    task = asyncio.create_task(_run())
    try:
        result = await asyncio.wait_for(asyncio.shield(task), timeout=bridge_after_ms / 1000.0)
        return result, None
    except TimeoutError:
        bridge = _ndjson({"text": random.choice(BRIDGE_PHRASES), "interim": True})
        # Now wait for the task to actually complete; no timeout.
        result = await task
        return result, bridge


async def token_stream_to_ndjson(
    tokens: AsyncIterator[str],
    *,
    chunk_chars: int = 12,
    first_flush_chars: int = 1,
) -> AsyncIterator[bytes]:
    """Buffer token-groups into ~chunk_chars-sized NDJSON interim chunks;
    emit the final (non-interim) chunk with whatever remains.

    The FIRST flush happens at first_flush_chars (default 1) — we get the
    very first token out to AgentPhone's TTS as fast as possible so the
    caller hears speech start within ~1s of the LLM emitting its first
    token. Subsequent flushes use chunk_chars (default 12 ≈ one short word)
    to keep TTS pipelined without spamming AP with one-char writes.

    chunk_chars is a soft target — we flush at the first token-group that
    pushes the buffer past it.
    """
    buffer = ""
    threshold = first_flush_chars
    async for token in tokens:
        buffer += token
        if len(buffer) >= threshold:
            yield _ndjson({"text": buffer, "interim": True})
            buffer = ""
            threshold = chunk_chars
    # Final chunk closes the turn (interim absent per HLD §11.2.3)
    if buffer:
        yield _ndjson({"text": buffer})
    else:
        # Empty final chunk still required so AP knows the stream is done.
        yield _ndjson({"text": ""})


def hangup_chunk(reason: str = "completed") -> bytes:
    return _ndjson({"text": "", "hangup": True, "reason": reason})
