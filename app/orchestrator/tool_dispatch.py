"""Tool-call marker detection in the LLM stream.

Phase 0 §C6 invocation pattern:

  The LLM emits free-form spoken text, optionally followed by a marker:

      <<TOOL request_manager_decision {"prompt":"...","options":[...],...}>>

  `scan_for_tool_call` consumes a token-group stream and yields a series of
  events:
    ("text", str)       - normal spoken text the orchestrator should stream
    ("marker_start", _) - we just saw "<<TOOL"; stop streaming text
    ("tool_call", dict) - we have a complete parsed call; dispatch it
    ("text", str)       - any text AFTER the marker (rare)
    ("done", _)         - stream closed

The orchestrator's turn loop reads these events: streams text through
the NDJSON wrapper, dispatches tool calls when complete, emits bridge
text from ToolResult.bridge_text, ends the turn if ToolResult.end_turn.

Upgrading to native OpenAI tool-call streaming later is a swap of this
file - the ToolRegistry contract above doesn't change.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Literal

from app.logging import get_logger
from app.orchestrator.tools.base import MARKER_CLOSE, MARKER_OPEN

log = get_logger(__name__)


ScanEvent = tuple[Literal["text", "tool_call", "error", "done"], Any]


async def scan_for_tool_calls(tokens: AsyncIterator[str]) -> AsyncIterator[ScanEvent]:
    """Stream-filter that pulls tool-call markers out of token chunks.

    Buffer just enough to detect MARKER_OPEN. While not in a marker, yield
    text as it arrives. Once MARKER_OPEN appears, accumulate until MARKER_CLOSE,
    parse, and yield ("tool_call", {name, args}). Anything after the marker
    is yielded as more text (uncommon but handled).
    """
    buffer = ""
    in_marker = False

    async for token in tokens:
        buffer += token
        while True:
            if not in_marker:
                idx = buffer.find(MARKER_OPEN)
                if idx == -1:
                    # No marker on the horizon - but hold back the last
                    # len(MARKER_OPEN)-1 chars in case the marker is split
                    # across token boundaries.
                    safe_emit = buffer[: max(0, len(buffer) - (len(MARKER_OPEN) - 1))]
                    if safe_emit:
                        yield ("text", safe_emit)
                        buffer = buffer[len(safe_emit) :]
                    break
                # Emit text before the marker, then enter marker mode.
                if idx > 0:
                    yield ("text", buffer[:idx])
                buffer = buffer[idx + len(MARKER_OPEN) :]
                in_marker = True
                continue
            # In marker: look for close
            close = buffer.find(MARKER_CLOSE)
            if close == -1:
                break  # need more tokens
            raw = buffer[:close].strip()
            buffer = buffer[close + len(MARKER_CLOSE) :]
            in_marker = False
            parsed = _parse_marker(raw)
            if parsed is None:
                yield ("error", f"malformed tool marker: {raw[:80]!r}")
            else:
                yield ("tool_call", parsed)

    # Stream done - flush remaining text
    if not in_marker and buffer:
        yield ("text", buffer)
    elif in_marker:
        yield ("error", f"unterminated tool marker: {buffer[:80]!r}")
    yield ("done", None)


def _parse_marker(raw: str) -> dict[str, Any] | None:
    """Parse `name {json}` (space-separated) into {name, args}."""
    space = raw.find(" ")
    if space == -1 or space == 0:
        return None
    name = raw[:space].strip()
    args_raw = raw[space + 1 :].strip()
    try:
        args = json.loads(args_raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(args, dict):
        return None
    return {"name": name, "args": args}
