"""Intake handlers (§C8) now call the brain provider.

Pure-logic verification with a fake brain + a stub session — the real
Postgres round-trip is covered in tests/integration.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.brain.base import (
    BrainPageSnapshot,
    BrainProvider,
    ManagerAuthoritativeConflict,
    TimelineEntry,
)
from app.services.intake_handlers import (
    CrossRefHandler,
    HandlerInput,
    OrgBrainHandler,
    RawSourceHandler,
)


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
    def __init__(self, *, conflict_on: set[str] | None = None) -> None:
        self.upserted: list[dict[str, Any]] = []
        self.timeline_appends: list[dict[str, Any]] = []
        self.conflict_on = conflict_on or set()

    async def ensure_schema(self, workspace_id):  # type: ignore[no-untyped-def]
        pass

    async def get_page(self, workspace_id, slug):  # type: ignore[no-untyped-def]
        return _snapshot(slug)

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
        if slug in self.conflict_on:
            raise ManagerAuthoritativeConflict(slug=slug)
        self.upserted.append(
            {
                "slug": slug,
                "kind": kind,
                "title": title,
                "compiled_truth": compiled_truth,
                "provenance_id": provenance_id,
                "manager_authoritative": manager_authoritative,
            }
        )
        return _snapshot(slug, manager=manager_authoritative)

    async def append_timeline(self, workspace_id, *, slug, entry):  # type: ignore[no-untyped-def]
        self.timeline_appends.append({"slug": slug, "entry_text": entry.text})
        return _snapshot(slug)

    async def list_versions(self, workspace_id, slug):  # type: ignore[no-untyped-def]
        return []

    async def soft_delete_page(self, workspace_id, slug):  # type: ignore[no-untyped-def]
        pass

    async def hybrid_search(self, workspace_id, query, *, k=8, types=None):  # type: ignore[no-untyped-def]
        return []


def _patch_provenance() -> Any:
    # Replace the in-handler ProvenanceRepo.create with a stub so tests
    # don't need a real DB session.
    target = "app.services.intake_handlers.ProvenanceRepo"

    class _StubProv:
        id = uuid4()

    class _StubRepo:
        def __init__(self, session):  # type: ignore[no-untyped-def]
            pass

        async def create(self, **kwargs):  # type: ignore[no-untyped-def]
            return _StubProv

    return patch(target, _StubRepo)


def _patch_app_session() -> Any:
    target = "app.services.intake_handlers.app_session"

    class _AsyncCM:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            session = AsyncMock()
            session.commit = AsyncMock(return_value=None)
            return session

        async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
            return False

    return patch(target, lambda: _AsyncCM())


async def test_org_brain_handler_upserts_page() -> None:
    brain = _FakeBrain()
    inputs = HandlerInput(
        workspace_id=uuid4(),
        organization_id=uuid4(),
        item_id=uuid4(),
        content_text="Acme Corp is renewing Q3, stage 3.",
        classification={
            "scope": "ORG_WIDE",
            "kind": "account",
            "suggested_slug": "accounts/acme-corp",
            "extracted_entities": [{"type": "company", "name": "Acme Corp"}],
            "confidence": 0.9,
            "reasoning": "explicit account mention",
        },
    )
    with _patch_provenance(), _patch_app_session():
        result = await OrgBrainHandler().ingest(inputs, brain=brain)
    assert result["action"] == "upserted_brain_page"
    assert result["slug"] == "accounts/acme-corp"
    assert len(brain.upserted) == 1
    assert brain.upserted[0]["title"] == "Acme Corp"


async def test_org_brain_handler_conflict_appends_timeline_and_flags_review() -> None:
    brain = _FakeBrain(conflict_on={"accounts/acme-corp"})
    inputs = HandlerInput(
        workspace_id=uuid4(),
        organization_id=uuid4(),
        item_id=uuid4(),
        content_text="Acme uses HubSpot.",
        classification={
            "scope": "ORG_WIDE",
            "kind": "account",
            "suggested_slug": "accounts/acme-corp",
            "extracted_entities": [{"type": "company", "name": "Acme Corp"}],
            "confidence": 0.9,
            "reasoning": "...",
        },
    )
    with _patch_provenance(), _patch_app_session():
        result = await OrgBrainHandler().ingest(inputs, brain=brain)
    assert result["action"] == "manager_authoritative_conflict"
    assert result["needs_review"] is True
    assert brain.upserted == []
    assert len(brain.timeline_appends) == 1


async def test_cross_ref_handler_writes_workspace_side() -> None:
    brain = _FakeBrain()
    inputs = HandlerInput(
        workspace_id=uuid4(),
        organization_id=uuid4(),
        item_id=uuid4(),
        content_text="Sarah owns Acme.",
        classification={
            "scope": "BOTH",
            "kind": "person",
            "suggested_slug": "accounts/acme-corp",
            "target_caller_id": str(uuid4()),
            "extracted_entities": [{"type": "company", "name": "Acme"}],
            "confidence": 0.95,
            "reasoning": "...",
        },
    )
    with _patch_provenance(), _patch_app_session():
        result = await CrossRefHandler().ingest(inputs, brain=brain)
    assert result["action"] == "upserted_workspace_side"
    assert result["workspace_side"]["action"] == "upserted_brain_page"
    assert len(brain.upserted) == 1


async def test_raw_source_handler_writes_one_page_per_entity() -> None:
    brain = _FakeBrain()
    inputs = HandlerInput(
        workspace_id=uuid4(),
        organization_id=uuid4(),
        item_id=uuid4(),
        content_text="(CRM rows)",
        classification={
            "scope": "RAW_SOURCE",
            "kind": "raw_document",
            "extracted_entities": [
                {"type": "company", "name": "Acme"},
                {"type": "company", "name": "Initech"},
                {"type": "person", "name": "Jane Doe"},
            ],
            "confidence": 0.9,
            "reasoning": "...",
        },
    )
    with _patch_provenance(), _patch_app_session():
        result = await RawSourceHandler().ingest(inputs, brain=brain)
    assert result["action"] == "fanout_raw_source"
    assert len(result["pages_upserted"]) == 3
    assert len(brain.upserted) == 3


@pytest.mark.parametrize(
    "entity_type,input_name,expected",
    [
        # 'account' is in the kind->slug-prefix map: account -> accounts/
        ("account", "Acme Corp", "accounts/acme-corp"),
        # 'person' maps to people/
        ("person", "Jane Doe", "people/jane-doe"),
        # 'company' isn't in the map, so the prefix is the raw kind.
        ("company", "Foo!@#Bar", "company/foobar"),
    ],
)
async def test_raw_source_slug_derivation(entity_type: str, input_name: str, expected: str) -> None:
    brain = _FakeBrain()
    inputs = HandlerInput(
        workspace_id=uuid4(),
        organization_id=uuid4(),
        item_id=uuid4(),
        content_text="x",
        classification={
            "scope": "RAW_SOURCE",
            "kind": "raw_document",
            "extracted_entities": [{"type": entity_type, "name": input_name}],
            "confidence": 0.9,
            "reasoning": "...",
        },
    )
    with _patch_provenance(), _patch_app_session():
        await RawSourceHandler().ingest(inputs, brain=brain)
    assert brain.upserted[0]["slug"] == expected


# Smoke that the TimelineEntry the handler builds has the expected shape.
def test_timeline_entry_smoke() -> None:
    e = TimelineEntry(ts=datetime.now(UTC), text="hi", provenance_id=uuid4(), tags=["t"])
    assert e.text == "hi"
    assert e.tags == ["t"]
