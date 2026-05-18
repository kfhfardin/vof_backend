"""CorrectionService - apply correction kinds + manager_authoritative side effects."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.brain.base import BrainPageSnapshot, BrainProvider, TimelineEntry
from app.errors import NotFound, Validation
from app.services.corrections import CorrectionKind, CorrectionService


def _snapshot(
    slug: str = "accounts/acme-corp",
    *,
    manager_authoritative: bool = False,
    deleted: bool = False,
    compiled_truth: str = "Acme uses HubSpot.",
) -> BrainPageSnapshot:
    return BrainPageSnapshot(
        slug=slug,
        kind="account",
        title="Acme Corp",
        compiled_truth=compiled_truth,
        timeline=[],
        tags=[],
        provenance_id=uuid4(),
        manager_authoritative=manager_authoritative,
        deleted_at=datetime.now(UTC) if deleted else None,
        version=1,
        updated_at=datetime.now(UTC),
    )


class _FakeBrain(BrainProvider):
    def __init__(self, page: BrainPageSnapshot | None) -> None:
        self.page = page
        self.upserted: list[dict[str, Any]] = []
        self.timeline_appends: list[dict[str, Any]] = []
        self.soft_deleted: list[str] = []

    async def ensure_schema(self, workspace_id):  # type: ignore[no-untyped-def]
        pass

    async def get_page(self, workspace_id, slug):  # type: ignore[no-untyped-def]
        return self.page

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
        self.upserted.append(
            {
                "slug": slug,
                "compiled_truth": compiled_truth,
                "manager_authoritative": manager_authoritative,
                "timeline_seed": timeline_seed.text if timeline_seed else None,
            }
        )
        self.page = _snapshot(
            slug, manager_authoritative=manager_authoritative, compiled_truth=compiled_truth
        )
        return self.page

    async def append_timeline(self, workspace_id, *, slug, entry):  # type: ignore[no-untyped-def]
        self.timeline_appends.append({"slug": slug, "entry_text": entry.text})
        return self.page or _snapshot(slug)

    async def list_versions(self, workspace_id, slug):  # type: ignore[no-untyped-def]
        return []

    async def soft_delete_page(self, workspace_id, slug):  # type: ignore[no-untyped-def]
        self.soft_deleted.append(slug)

    async def hybrid_search(self, workspace_id, query, *, k=8, types=None):  # type: ignore[no-untyped-def]
        return []


class _FakeProvRepo:
    def __init__(self, session):  # type: ignore[no-untyped-def]
        self.created: list[dict[str, Any]] = []

    async def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.created.append(kwargs)

        class _P:
            id = uuid4()

        return _P


def _patch_prov_repo():  # type: ignore[no-untyped-def]
    return patch("app.services.corrections.ProvenanceRepo", _FakeProvRepo)


def _fake_session():  # type: ignore[no-untyped-def]
    s = AsyncMock()
    s.commit = AsyncMock(return_value=None)
    return s


def _patch_cascade_inline(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CORRECTION_CASCADE_INLINE", "1")


async def test_replace_compiled_truth_writes_new_version_and_marks_manager_authoritative(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    _patch_cascade_inline(monkeypatch)
    brain = _FakeBrain(page=_snapshot(manager_authoritative=False, compiled_truth="Acme uses HubSpot."))
    with _patch_prov_repo():
        svc = CorrectionService(_fake_session(), brain=brain)
        snapshot = await svc.apply(
            workspace_id=uuid4(),
            target_slug="accounts/acme-corp",
            kind=CorrectionKind.REPLACE_COMPILED_TRUTH,
            payload={"compiled_truth": "Acme uses Salesforce."},
            rationale="Rep corrected on call",
            corrected_by_user_id=uuid4(),
        )
    assert snapshot is not None
    assert len(brain.upserted) == 1
    upsert = brain.upserted[0]
    assert upsert["compiled_truth"] == "Acme uses Salesforce."
    assert upsert["manager_authoritative"] is True
    assert "[CORRECTED by manager]" in (upsert["timeline_seed"] or "")


async def test_replace_compiled_truth_rejects_empty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_cascade_inline(monkeypatch)
    brain = _FakeBrain(page=_snapshot())
    with _patch_prov_repo(), pytest.raises(Validation, match="non-empty"):
        svc = CorrectionService(_fake_session(), brain=brain)
        await svc.apply(
            workspace_id=uuid4(),
            target_slug="accounts/acme-corp",
            kind=CorrectionKind.REPLACE_COMPILED_TRUTH,
            payload={"compiled_truth": "   "},
            rationale=None,
            corrected_by_user_id=uuid4(),
        )


async def test_replace_compiled_truth_creates_page_when_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Per the design, a Manager can correct a slug that doesn't exist yet -
    the correction creates the page outright with manager_authoritative=True.
    Other kinds (soft_delete, append_timeline) require the page to exist."""
    _patch_cascade_inline(monkeypatch)
    brain = _FakeBrain(page=None)
    with _patch_prov_repo():
        svc = CorrectionService(_fake_session(), brain=brain)
        snapshot = await svc.apply(
            workspace_id=uuid4(),
            target_slug="accounts/brand-new",
            kind=CorrectionKind.REPLACE_COMPILED_TRUTH,
            payload={"compiled_truth": "fresh fact", "title": "Brand New", "kind": "account"},
            rationale=None,
            corrected_by_user_id=uuid4(),
        )
    assert snapshot is not None
    assert brain.upserted[0]["manager_authoritative"] is True


async def test_soft_delete_appends_timeline_then_deletes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_cascade_inline(monkeypatch)
    brain = _FakeBrain(page=_snapshot())
    with _patch_prov_repo():
        svc = CorrectionService(_fake_session(), brain=brain)
        await svc.apply(
            workspace_id=uuid4(),
            target_slug="accounts/acme-corp",
            kind=CorrectionKind.SOFT_DELETE_PAGE,
            payload={},
            rationale="duplicate",
            corrected_by_user_id=uuid4(),
        )
    assert len(brain.timeline_appends) == 1
    assert "[DELETED by manager]" in brain.timeline_appends[0]["entry_text"]
    assert brain.soft_deleted == ["accounts/acme-corp"]


async def test_soft_delete_not_found_raises(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_cascade_inline(monkeypatch)
    brain = _FakeBrain(page=None)
    with _patch_prov_repo(), pytest.raises(NotFound):
        svc = CorrectionService(_fake_session(), brain=brain)
        await svc.apply(
            workspace_id=uuid4(),
            target_slug="accounts/missing",
            kind=CorrectionKind.SOFT_DELETE_PAGE,
            payload={},
            rationale=None,
            corrected_by_user_id=uuid4(),
        )


async def test_append_timeline_entry_only(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_cascade_inline(monkeypatch)
    brain = _FakeBrain(page=_snapshot())
    with _patch_prov_repo():
        svc = CorrectionService(_fake_session(), brain=brain)
        await svc.apply(
            workspace_id=uuid4(),
            target_slug="accounts/acme-corp",
            kind=CorrectionKind.APPEND_TIMELINE_ENTRY,
            payload={"text": "buyer mentioned a board check-in"},
            rationale=None,
            corrected_by_user_id=uuid4(),
        )
    assert len(brain.timeline_appends) == 1
    assert "[NOTE by manager]" in brain.timeline_appends[0]["entry_text"]
    assert "board check-in" in brain.timeline_appends[0]["entry_text"]
    assert brain.upserted == []


async def test_unsupported_kind_raises(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_cascade_inline(monkeypatch)
    brain = _FakeBrain(page=_snapshot())
    with _patch_prov_repo(), pytest.raises(Validation):
        svc = CorrectionService(_fake_session(), brain=brain)
        await svc.apply(
            workspace_id=uuid4(),
            target_slug="accounts/acme-corp",
            kind="merge_entities",  # not in Phase 0
            payload={},
            rationale=None,
            corrected_by_user_id=uuid4(),
        )


def test_request_correction_tool_registered() -> None:
    from app.orchestrator.tools import RequestCorrection, ToolRegistry

    assert isinstance(ToolRegistry.get("request_correction"), RequestCorrection)
    described = next(t for t in ToolRegistry.describe() if t["name"] == "request_correction")
    assert "slug" in described["input_schema"]["properties"]
    assert "kind" in described["input_schema"]["properties"]
    assert "text" in described["input_schema"]["properties"]


def test_correction_cascade_test_mode(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.workers.correction_cascade import _is_inline_mode, job_id

    monkeypatch.delenv("CORRECTION_CASCADE_INLINE", raising=False)
    assert _is_inline_mode() is False
    monkeypatch.setenv("CORRECTION_CASCADE_INLINE", "1")
    assert _is_inline_mode() is True
    assert job_id(uuid4(), "accounts/acme", "replace_compiled_truth").startswith("cc:")


def _unused_import() -> TimelineEntry:
    """Keep TimelineEntry referenced so the import doesn't get culled."""
    return TimelineEntry(ts=datetime.now(UTC), text="x", provenance_id=None)
