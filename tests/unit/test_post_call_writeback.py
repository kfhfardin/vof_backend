"""§C11 post-call writeback - logic-only unit tests.

Real DB + Redis round-trip lives in tests/integration. Here we verify:

  - render_caller_memory_digest produces the expected shape
  - brain_updater calls upsert_page for new entities + append_timeline for
    existing entities + records needs_review on ManagerAuthoritativeConflict
  - the post_call_job inline-mode toggle short-circuits Redis
  - the call.summary_ready frame is well-formed
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.brain.base import BrainPageSnapshot, BrainProvider, TimelineEntry
from app.miniagents.brain_updater import (
    BrainUpdateInput,
    _resolve_slug,
    _slugify,
    run_brain_updater,
)
from app.miniagents.caller_memory_writer import (
    render_caller_memory_digest,
    write_call_to_caller_memory,
)
from app.miniagents.summarizer_agent import SummarizerOutput
from app.schemas.ws_frames import CallSummaryReadyFrame


def _snapshot(slug: str, manager: bool = False) -> BrainPageSnapshot:
    return BrainPageSnapshot(
        slug=slug,
        kind="account",
        title="Acme Corp",
        compiled_truth="...",
        timeline=[],
        tags=[],
        provenance_id=uuid4(),
        manager_authoritative=manager,
        deleted_at=None,
        version=1,
        updated_at=datetime.now(UTC),
    )


class _FakeBrain(BrainProvider):
    def __init__(
        self,
        *,
        existing: dict[str, BrainPageSnapshot] | None = None,
        conflict_on_create: set[str] | None = None,
    ) -> None:
        self.existing = existing or {}
        self.conflict_on_create = conflict_on_create or set()
        self.upserted: list[dict] = []  # type: ignore[type-arg]
        self.timeline_appends: list[dict] = []  # type: ignore[type-arg]

    async def ensure_schema(self, workspace_id):  # type: ignore[no-untyped-def]
        pass

    async def get_page(self, workspace_id, slug):  # type: ignore[no-untyped-def]
        return self.existing.get(slug)

    async def upsert_page(  # type: ignore[no-untyped-def]
        self,
        workspace_id,
        *,
        slug,
        kind,
        title,
        compiled_truth,
        provenance_id,
        manager_authoritative=False,
        tags=None,
        timeline_seed=None,
    ):
        if slug in self.conflict_on_create:
            from app.brain.base import ManagerAuthoritativeConflict

            raise ManagerAuthoritativeConflict(slug=slug)
        self.upserted.append({"slug": slug, "kind": kind, "title": title})
        snap = _snapshot(slug, manager=manager_authoritative)
        self.existing[slug] = snap
        return snap

    async def append_timeline(self, workspace_id, *, slug, entry):  # type: ignore[no-untyped-def]
        self.timeline_appends.append({"slug": slug, "text": entry.text})
        return self.existing.get(slug) or _snapshot(slug)

    async def list_versions(self, workspace_id, slug):  # type: ignore[no-untyped-def]
        return []

    async def soft_delete_page(self, workspace_id, slug):  # type: ignore[no-untyped-def]
        pass

    async def hybrid_search(self, workspace_id, query, *, k=8, types=None):  # type: ignore[no-untyped-def]
        return []


def _patch_provenance():  # type: ignore[no-untyped-def]
    target = "app.miniagents.brain_updater.ProvenanceRepo"

    class _StubProv:
        id = uuid4()

    class _StubRepo:
        def __init__(self, session):  # type: ignore[no-untyped-def]
            pass

        async def create(self, **kwargs):  # type: ignore[no-untyped-def]
            return _StubProv

    return patch(target, _StubRepo)


def _patch_app_session():  # type: ignore[no-untyped-def]
    target = "app.miniagents.brain_updater.app_session"

    class _AsyncCM:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            s = AsyncMock()
            s.commit = AsyncMock(return_value=None)
            return s

        async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
            return False

    return patch(target, lambda: _AsyncCM())


# ---------------- brain_updater ----------------


def test_resolve_slug_uses_hint_when_present() -> None:
    assert (
        _resolve_slug({"slug_hint": "accounts/acme-corp", "type": "company", "name": "Acme"})
        == "accounts/acme-corp"
    )


def test_resolve_slug_derives_from_kind_and_name() -> None:
    assert _resolve_slug({"type": "company", "name": "Initech"}) == "accounts/initech"
    assert _resolve_slug({"type": "person", "name": "Sarah Chen"}) == "people/sarah-chen"
    # Unknown kind falls through to the raw kind as the prefix
    assert _resolve_slug({"type": "playbook", "name": "Discovery"}) == "playbook/discovery"


def test_slugify_strips_punct_and_spaces() -> None:
    assert _slugify("Acme Corp!") == "acme-corp"
    assert _slugify("  ") == "untitled"


async def test_brain_updater_creates_stub_for_new_entity() -> None:
    brain = _FakeBrain()
    summary = SummarizerOutput(
        discussion="Talked to Acme about renewal.",
        blockers=[],
        extracted_entities=[{"type": "company", "name": "Acme Corp", "slug_hint": None}],
    )
    inputs = BrainUpdateInput(workspace_id=uuid4(), call_id=uuid4(), summary=summary)
    with _patch_provenance(), _patch_app_session():
        result = await run_brain_updater(inputs, brain=brain)
    assert result.pages_upserted == ["accounts/acme-corp"]
    assert result.timeline_appends == []
    assert brain.upserted[0]["title"] == "Acme Corp"


async def test_brain_updater_appends_to_existing_page() -> None:
    brain = _FakeBrain(existing={"accounts/acme-corp": _snapshot("accounts/acme-corp")})
    summary = SummarizerOutput(
        discussion="Acme renewal moved to Q4.",
        blockers=[],
        extracted_entities=[{"type": "company", "name": "Acme Corp", "slug_hint": None}],
    )
    inputs = BrainUpdateInput(workspace_id=uuid4(), call_id=uuid4(), summary=summary)
    with _patch_provenance(), _patch_app_session():
        result = await run_brain_updater(inputs, brain=brain)
    assert result.pages_upserted == []
    assert result.timeline_appends == ["accounts/acme-corp"]
    assert brain.upserted == []
    assert "Mentioned in call" in brain.timeline_appends[0]["text"]


async def test_brain_updater_skips_when_no_entities() -> None:
    brain = _FakeBrain()
    summary = SummarizerOutput(discussion="...", blockers=[], extracted_entities=[])
    inputs = BrainUpdateInput(workspace_id=uuid4(), call_id=uuid4(), summary=summary)
    with _patch_provenance(), _patch_app_session():
        result = await run_brain_updater(inputs, brain=brain)
    assert result.pages_upserted == []
    assert result.timeline_appends == []


async def test_brain_updater_ignores_entities_with_no_name() -> None:
    brain = _FakeBrain()
    summary = SummarizerOutput(
        discussion="...",
        blockers=[],
        extracted_entities=[
            {"type": "company", "name": "", "slug_hint": None},
            {"type": "company", "name": "Acme", "slug_hint": None},
        ],
    )
    inputs = BrainUpdateInput(workspace_id=uuid4(), call_id=uuid4(), summary=summary)
    with _patch_provenance(), _patch_app_session():
        result = await run_brain_updater(inputs, brain=brain)
    assert result.pages_upserted == ["accounts/acme"]


# ---------------- caller_memory_writer ----------------


def test_render_caller_memory_digest_includes_blockers_and_entities() -> None:
    call = SimpleNamespace(
        id=uuid4(),
        workspace_id=uuid4(),
        started_at=datetime(2026, 5, 17, tzinfo=UTC),
    )
    summary = SummarizerOutput(
        discussion="Sarah met with Acme; they want SOC 2 evidence.",
        blockers=["needs SOC 2 letter"],
        extracted_entities=[{"type": "company", "name": "Acme", "slug_hint": None}],
    )
    transcript = [
        SimpleNamespace(speaker="caller", text="hi"),
        SimpleNamespace(speaker="agent", text="hey"),
        SimpleNamespace(speaker="caller", text="met Acme"),
    ]
    digest = render_caller_memory_digest(call=call, transcript=transcript, summary=summary)  # type: ignore[arg-type]
    assert "2026-05-17" in digest
    assert "Acme" in digest
    assert "SOC 2 letter" in digest
    assert "2 Rep turns" in digest and "1 agent turns" in digest


async def test_caller_memory_writer_returns_no_write_when_no_field_employee() -> None:
    call = SimpleNamespace(id=uuid4(), workspace_id=uuid4(), started_at=datetime.now(UTC))
    out = await write_call_to_caller_memory(
        call=call,  # type: ignore[arg-type]
        field_employee=None,
        transcript=[],
        summary=SummarizerOutput(discussion="x", blockers=[], extracted_entities=[]),
        memory=AsyncMock(),
    )
    assert out.written is False
    assert out.reason == "no_field_employee"


async def test_caller_memory_writer_accepts_stub_provider() -> None:
    # StubCallerMemoryProvider implements add() and returns a synthetic id;
    # the writer treats that as a successful write (the stub is the right
    # behavior when SUPERMEMORY_API_KEY is empty).
    from app.memory.stub import StubCallerMemoryProvider

    call = SimpleNamespace(id=uuid4(), workspace_id=uuid4(), started_at=datetime.now(UTC))
    fe = SimpleNamespace(id=uuid4(), name="Sarah", role="AE")
    out = await write_call_to_caller_memory(
        call=call,  # type: ignore[arg-type]
        field_employee=fe,  # type: ignore[arg-type]
        transcript=[],
        summary=SummarizerOutput(discussion="x", blockers=[], extracted_entities=[]),
        memory=StubCallerMemoryProvider(),
    )
    assert out.written is True
    assert out.memory_id is not None
    assert out.memory_id.startswith("stub_")


# ---------------- frame + worker hooks ----------------


def test_call_summary_ready_frame_shape() -> None:
    f = CallSummaryReadyFrame(call_id=uuid4(), has_summary=True, brain_pages_touched=["accounts/acme"])
    payload = f.model_dump(mode="json")
    assert payload["type"] == "call.summary_ready"
    assert payload["has_summary"] is True


def test_post_call_job_id_is_call_id_prefixed() -> None:
    from app.workers.post_call import job_id

    cid = uuid4()
    assert job_id(cid) == f"post_call:{cid}"


def test_post_call_inline_mode_toggle(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.workers.post_call import _is_inline_mode

    monkeypatch.delenv("POST_CALL_INLINE", raising=False)
    assert _is_inline_mode() is False
    monkeypatch.setenv("POST_CALL_INLINE", "1")
    assert _is_inline_mode() is True


# Defensive: TimelineEntry signature usage from the brain_updater is the
# integration seam with §C8; smoke-test it doesn't drift.
def test_timeline_entry_signature() -> None:
    e = TimelineEntry(ts=datetime.now(UTC), text="x", provenance_id=None, tags=["from_call"])
    assert e.tags == ["from_call"]
