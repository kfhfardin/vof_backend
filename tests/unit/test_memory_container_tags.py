"""Container-tag scheme + writer wiring tests.

These verify our domain conventions hold without needing real Supermemory:
  - tags are derived from (workspace_id, field_employee_id)
  - StubCallerMemoryProvider implements the full new interface
  - caller_memory_writer passes both tags every time
  - retrieval passes both tags on per-turn search and single tag on profile

The full Supermemory round-trip (write, search, isolation) lives in the
smoke probe (`smoke.supermemory --mode smoke`).
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.memory.base import (
    CallerMemoryProvider,
    caller_tag,
    container_tags_for,
    workspace_tag,
)
from app.memory.stub import StubCallerMemoryProvider
from app.miniagents.caller_memory_writer import (
    render_caller_memory_digest,
    write_call_to_caller_memory,
)
from app.miniagents.summarizer_agent import SummarizerOutput
from app.orchestrator.retrieval import Retriever

# ---------------- Tag scheme ----------------


def test_caller_tag_shape() -> None:
    fe = uuid4()
    assert caller_tag(fe) == f"caller_{fe}"


def test_workspace_tag_shape() -> None:
    ws = uuid4()
    assert workspace_tag(ws) == f"workspace_{ws}"


def test_container_tags_for_includes_both() -> None:
    ws = uuid4()
    fe = uuid4()
    tags = container_tags_for(ws, fe)
    assert tags[0] == f"caller_{fe}"
    assert tags[1] == f"workspace_{ws}"


# ---------------- Stub provider ----------------


async def test_stub_implements_full_interface() -> None:
    stub = StubCallerMemoryProvider()
    await stub.ensure_namespace(uuid4())
    mid = await stub.add(container_tags=["caller_x"], content="hi")
    assert mid.startswith("stub_")
    assert await stub.search(container_tags=["caller_x"], query="?") == []
    assert await stub.get_profile("caller_x") is None
    await stub.delete(container_tag="caller_x", memory_id=mid)  # noop


# ---------------- Writer ----------------


async def test_writer_passes_both_caller_and_workspace_tags() -> None:
    """The writer must tag every memory with caller_{fe} AND workspace_{ws}."""
    ws = uuid4()
    fe_id = uuid4()
    call_id = uuid4()
    call = SimpleNamespace(id=call_id, workspace_id=ws, started_at=datetime.now(UTC))
    fe = SimpleNamespace(id=fe_id, name="Sarah", role="AE")
    transcript: list[Any] = []
    summary = SummarizerOutput(
        discussion="met Acme", blockers=[], extracted_entities=[{"type": "company", "name": "Acme"}]
    )

    seen_tags: list[list[str]] = []

    class _CapturingProvider(CallerMemoryProvider):
        async def ensure_namespace(self, workspace_id):  # type: ignore[no-untyped-def]
            pass

        async def add(self, *, container_tags, content, metadata=None):  # type: ignore[no-untyped-def]
            seen_tags.append(list(container_tags))
            return "mem_xyz"

        async def search(self, *, container_tags, query, k=5):  # type: ignore[no-untyped-def]
            return []

        async def get_profile(self, container_tag):  # type: ignore[no-untyped-def]
            return None

        async def delete(self, *, container_tag, memory_id):  # type: ignore[no-untyped-def]
            pass

    result = await write_call_to_caller_memory(
        call=call,  # type: ignore[arg-type]
        field_employee=fe,  # type: ignore[arg-type]
        transcript=transcript,
        summary=summary,
        memory=_CapturingProvider(),
    )
    assert result.written is True
    assert result.memory_id == "mem_xyz"
    assert seen_tags == [[f"caller_{fe_id}", f"workspace_{ws}"]]


async def test_writer_returns_no_write_without_field_employee() -> None:
    call = SimpleNamespace(id=uuid4(), workspace_id=uuid4(), started_at=datetime.now(UTC))
    result = await write_call_to_caller_memory(
        call=call,  # type: ignore[arg-type]
        field_employee=None,
        transcript=[],
        summary=SummarizerOutput(discussion="x", blockers=[], extracted_entities=[]),
        memory=StubCallerMemoryProvider(),
    )
    assert result.written is False
    assert result.reason == "no_field_employee"


async def test_writer_returns_failure_when_provider_raises() -> None:
    ws = uuid4()
    fe = SimpleNamespace(id=uuid4(), name="x", role=None)
    call = SimpleNamespace(id=uuid4(), workspace_id=ws, started_at=datetime.now(UTC))

    class _BoomProvider(CallerMemoryProvider):
        async def ensure_namespace(self, workspace_id):  # type: ignore[no-untyped-def]
            pass

        async def add(self, *, container_tags, content, metadata=None):  # type: ignore[no-untyped-def]
            raise RuntimeError("provider down")

        async def search(self, *, container_tags, query, k=5):  # type: ignore[no-untyped-def]
            return []

        async def get_profile(self, container_tag):  # type: ignore[no-untyped-def]
            return None

        async def delete(self, *, container_tag, memory_id):  # type: ignore[no-untyped-def]
            pass

    result = await write_call_to_caller_memory(
        call=call,  # type: ignore[arg-type]
        field_employee=fe,  # type: ignore[arg-type]
        transcript=[],
        summary=SummarizerOutput(discussion="x", blockers=[], extracted_entities=[]),
        memory=_BoomProvider(),
    )
    assert result.written is False
    assert "provider down" in (result.reason or "")


# ---------------- Digest renderer ----------------


def test_digest_includes_essentials() -> None:
    call = SimpleNamespace(id=uuid4(), workspace_id=uuid4(), started_at=datetime(2026, 5, 17, tzinfo=UTC))
    summary = SummarizerOutput(
        discussion="discussed renewal",
        blockers=["SOC 2 letter"],
        extracted_entities=[{"type": "company", "name": "Acme"}],
    )
    transcript = [
        SimpleNamespace(speaker="caller", text="hi"),
        SimpleNamespace(speaker="agent", text="hey"),
    ]
    d = render_caller_memory_digest(call=call, transcript=transcript, summary=summary)  # type: ignore[arg-type]
    assert "2026-05-17" in d
    assert "renewal" in d
    assert "SOC 2 letter" in d
    assert "Acme" in d


# ---------------- Retriever passes correct tags ----------------


async def test_retriever_for_turn_uses_single_caller_tag() -> None:
    """Per-turn retrieval must search with [caller_tag] ONLY, not
    [caller_tag, workspace_tag]. Supermemory's container_tags is OR-matching
    (verified against the live API), so the two-tag pattern would leak
    cross-rep memories via the shared workspace tag."""
    ws = uuid4()
    fe = uuid4()
    seen: dict[str, Any] = {}

    class _Memory(CallerMemoryProvider):
        async def ensure_namespace(self, workspace_id):  # type: ignore[no-untyped-def]
            pass

        async def add(self, *, container_tags, content, metadata=None):  # type: ignore[no-untyped-def]
            return "x"

        async def search(self, *, container_tags, query, k=5):  # type: ignore[no-untyped-def]
            seen["tags"] = list(container_tags)
            seen["query"] = query
            return []

        async def get_profile(self, container_tag):  # type: ignore[no-untyped-def]
            return None

        async def delete(self, *, container_tag, memory_id):  # type: ignore[no-untyped-def]
            pass

    class _Brain:
        async def hybrid_search(self, workspace_id, query, *, k=8, types=None):  # type: ignore[no-untyped-def]
            return []

    r = Retriever(memory=_Memory(), brain=_Brain())  # type: ignore[arg-type]
    await r.for_turn(workspace_id=ws, field_employee_id=fe, query="acme")
    assert seen["tags"] == [f"caller_{fe}"]
    assert f"workspace_{ws}" not in seen["tags"], (
        "Including the workspace tag would leak cross-rep memories under "
        "Supermemory's OR-matching container_tags semantic."
    )
    assert seen["query"] == "acme"


async def test_retriever_for_turn_skips_search_without_field_employee() -> None:
    """Unprofiled caller has no field_employee yet - retrieval still works
    but caller memory comes back empty without any search call."""
    ws = uuid4()

    class _Memory(CallerMemoryProvider):
        def __init__(self) -> None:
            self.search_calls: list[Any] = []

        async def ensure_namespace(self, workspace_id):  # type: ignore[no-untyped-def]
            pass

        async def add(self, *, container_tags, content, metadata=None):  # type: ignore[no-untyped-def]
            return "x"

        async def search(self, *, container_tags, query, k=5):  # type: ignore[no-untyped-def]
            self.search_calls.append((container_tags, query))
            return []

        async def get_profile(self, container_tag):  # type: ignore[no-untyped-def]
            return None

        async def delete(self, *, container_tag, memory_id):  # type: ignore[no-untyped-def]
            pass

    class _Brain:
        async def hybrid_search(self, workspace_id, query, *, k=8, types=None):  # type: ignore[no-untyped-def]
            return []

    mem = _Memory()
    r = Retriever(memory=mem, brain=_Brain())  # type: ignore[arg-type]
    out = await r.for_turn(workspace_id=ws, field_employee_id=None, query="x")
    assert out.caller_hits == []
    assert mem.search_calls == []


async def test_retriever_prewarm_uses_single_caller_tag_for_profile() -> None:
    ws = uuid4()
    fe = uuid4()
    seen: dict[str, Any] = {}

    class _Memory(CallerMemoryProvider):
        async def ensure_namespace(self, workspace_id):  # type: ignore[no-untyped-def]
            pass

        async def add(self, *, container_tags, content, metadata=None):  # type: ignore[no-untyped-def]
            return "x"

        async def search(self, *, container_tags, query, k=5):  # type: ignore[no-untyped-def]
            return []

        async def get_profile(self, container_tag):  # type: ignore[no-untyped-def]
            seen["tag"] = container_tag
            return None

        async def delete(self, *, container_tag, memory_id):  # type: ignore[no-untyped-def]
            pass

    class _Brain:
        async def hybrid_search(self, workspace_id, query, *, k=8, types=None):  # type: ignore[no-untyped-def]
            return []

    r = Retriever(memory=_Memory(), brain=_Brain())  # type: ignore[arg-type]
    await r.prewarm_starter(workspace_id=ws, field_employee_id=fe)
    assert seen["tag"] == f"caller_{fe}"


# ---------------- Real SupermemoryCallerMemoryProvider construction ----------------


def test_supermemory_provider_rejects_empty_key() -> None:
    from app.memory.supermemory import SupermemoryCallerMemoryProvider

    with pytest.raises(ValueError, match="non-empty API key"):
        SupermemoryCallerMemoryProvider(api_key="")
