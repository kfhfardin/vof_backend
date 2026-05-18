"""Marker-based tool-call detector + ToolRegistry surface."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.orchestrator.tool_dispatch import scan_for_tool_calls
from app.orchestrator.tools import (
    EndCall,
    OrchestratorTool,
    RequestManagerDecision,
    ToolRegistry,
    encode_tool_marker,
)


async def _stream(parts: list[str]) -> AsyncIterator[str]:
    for p in parts:
        yield p
        await asyncio.sleep(0)


async def _collect(stream: AsyncIterator) -> list[tuple]:  # type: ignore[type-arg]
    return [event async for event in stream]


async def test_text_only_stream_yields_text_then_done() -> None:
    events = await _collect(scan_for_tool_calls(_stream(["Hello ", "Sarah", "."])))
    text_parts = [p for k, p in events if k == "text"]
    assert "".join(text_parts) == "Hello Sarah."
    assert events[-1] == ("done", None)


async def test_marker_at_end_yields_tool_call() -> None:
    marker = encode_tool_marker(
        "request_manager_decision",
        {"prompt": "approve discount?", "options": ["yes", "no"], "decision_class": "inline"},
    )
    events = await _collect(scan_for_tool_calls(_stream(["Hold on. ", marker])))
    types = [k for k, _ in events]
    assert "text" in types
    assert "tool_call" in types
    tool_event = next(p for k, p in events if k == "tool_call")
    assert tool_event["name"] == "request_manager_decision"
    assert tool_event["args"]["options"] == ["yes", "no"]


async def test_marker_split_across_chunks_still_parses() -> None:
    marker = encode_tool_marker("end_call", {"reason": "completed"})
    # Slice the marker at an awkward point to verify the boundary handling
    half = len(marker) // 2
    events = await _collect(scan_for_tool_calls(_stream(["bye. ", marker[:half], marker[half:]])))
    tool_event = next(p for k, p in events if k == "tool_call")
    assert tool_event["name"] == "end_call"


async def test_malformed_marker_emits_error_event() -> None:
    events = await _collect(scan_for_tool_calls(_stream(["text ", "<<TOOL not-json-here>>"])))
    types = [k for k, _ in events]
    assert "error" in types


async def test_unterminated_marker_emits_error_on_close() -> None:
    events = await _collect(scan_for_tool_calls(_stream(["text ", "<<TOOL incomplete"])))
    assert any(k == "error" for k, _ in events)


def test_tool_registry_has_phase_0_tools() -> None:
    names = ToolRegistry.names()
    assert "request_manager_decision" in names
    assert "end_call" in names


def test_tool_registry_describe_carries_schema() -> None:
    described = {t["name"]: t for t in ToolRegistry.describe()}
    schema = described["request_manager_decision"]["input_schema"]
    assert "properties" in schema
    assert "prompt" in schema["properties"]
    assert "options" in schema["properties"]


def test_tool_registry_duplicate_register_raises() -> None:
    class _Dupe(OrchestratorTool):
        from pydantic import BaseModel as _BM

        name = "request_manager_decision"
        description = "x"
        input_schema = _BM  # type: ignore[assignment]

        async def run(self, ctx, inputs):  # type: ignore[no-untyped-def]
            return None  # pragma: no cover

    with pytest.raises(ValueError, match="already registered"):
        ToolRegistry.register(_Dupe())


def test_concrete_tools_are_registered_instances() -> None:
    rmd = ToolRegistry.get("request_manager_decision")
    end = ToolRegistry.get("end_call")
    assert isinstance(rmd, RequestManagerDecision)
    assert isinstance(end, EndCall)
