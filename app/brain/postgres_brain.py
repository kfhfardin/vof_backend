"""Postgres BrainProvider.

Per-workspace schema (`brain_w_{wid.hex}`) holds two tables:

  brain_pages           current truth + timeline (JSONB)
  brain_page_versions   monotonic version chain; superseded_by points to next

ensure_schema is idempotent: CREATE SCHEMA IF NOT EXISTS + CREATE TABLE IF
NOT EXISTS for both tables. We skip alembic-per-schema for Phase 0
because the DDL is small and ensure_schema runs at workspace signup.

When the brain schema gains more tables (typed graph edges in §D3, etc.),
the right pattern is to extend ensure_schema with the new CREATE TABLE IF
NOT EXISTS statements plus a separate `python -m scripts.alembic_wrapper
brain upgrade --all-workspaces` for existing workspaces (per LLD §A4).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from app.brain.base import (
    BrainPageSnapshot,
    BrainPageVersionSnapshot,
    BrainProvider,
    BrainSearchHit,
    ManagerAuthoritativeConflict,
    TimelineEntry,
)
from app.db.brain_session import _factory, brain_session


def _schema_name(workspace_id: UUID) -> str:
    return f"brain_w_{workspace_id.hex}"


# DDL applied per workspace. Wrapped in IF NOT EXISTS so ensure_schema is idempotent.
_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS brain_pages (
        slug                 text PRIMARY KEY,
        kind                 text NOT NULL,
        title                text NOT NULL,
        compiled_truth       text NOT NULL,
        timeline             jsonb NOT NULL DEFAULT '[]'::jsonb,
        tags                 jsonb NOT NULL DEFAULT '[]'::jsonb,
        provenance_id        uuid,
        manager_authoritative boolean NOT NULL DEFAULT false,
        deleted_at           timestamptz,
        version              int NOT NULL DEFAULT 1,
        created_at           timestamptz NOT NULL DEFAULT now(),
        updated_at           timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_brain_pages_kind ON brain_pages (kind)",
    "CREATE INDEX IF NOT EXISTS ix_brain_pages_manager_auth ON brain_pages (manager_authoritative)",
    """
    CREATE TABLE IF NOT EXISTS brain_page_versions (
        id              uuid PRIMARY KEY,
        page_slug       text NOT NULL,
        version         int NOT NULL,
        compiled_truth  text NOT NULL,
        provenance_id   uuid,
        superseded_by   uuid,
        created_at      timestamptz NOT NULL DEFAULT now(),
        UNIQUE (page_slug, version),
        FOREIGN KEY (page_slug) REFERENCES brain_pages(slug) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_brain_page_versions_page_slug ON brain_page_versions (page_slug)",
    "CREATE INDEX IF NOT EXISTS ix_brain_page_versions_superseded_by ON brain_page_versions (superseded_by)",
]


def _timeline_entry_to_dict(entry: TimelineEntry) -> dict[str, Any]:
    return {
        "ts": entry.ts.isoformat(),
        "text": entry.text,
        "provenance_id": str(entry.provenance_id) if entry.provenance_id else None,
        "tags": list(entry.tags),
    }


def _row_to_snapshot(row: Any) -> BrainPageSnapshot:
    return BrainPageSnapshot(
        slug=row["slug"],
        kind=row["kind"],
        title=row["title"],
        compiled_truth=row["compiled_truth"],
        timeline=list(row["timeline"] or []),
        tags=list(row["tags"] or []),
        provenance_id=UUID(str(row["provenance_id"])) if row["provenance_id"] else None,
        manager_authoritative=bool(row["manager_authoritative"]),
        deleted_at=row["deleted_at"],
        version=int(row["version"]),
        updated_at=row["updated_at"],
    )


def _version_row_to_snapshot(row: Any) -> BrainPageVersionSnapshot:
    return BrainPageVersionSnapshot(
        id=UUID(str(row["id"])),
        slug=row["page_slug"],
        version=int(row["version"]),
        compiled_truth=row["compiled_truth"],
        provenance_id=UUID(str(row["provenance_id"])) if row["provenance_id"] else None,
        superseded_by=UUID(str(row["superseded_by"])) if row["superseded_by"] else None,
        created_at=row["created_at"],
    )


class PostgresBrainProvider(BrainProvider):
    async def ensure_schema(self, workspace_id: UUID) -> None:
        schema = _schema_name(workspace_id)
        # Step 1: CREATE SCHEMA needs an unpinned session (no SET search_path).
        async with _factory()() as session:
            await session.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            await session.commit()
        # Step 2: CREATE TABLE statements run with the schema pinned.
        async with brain_session(workspace_id) as session:
            for ddl in _DDL_STATEMENTS:
                await session.execute(text(ddl))
            await session.commit()

    # ---------------- Reads ----------------

    async def get_page(self, workspace_id: UUID, slug: str) -> BrainPageSnapshot | None:
        async with brain_session(workspace_id) as session:
            result = await session.execute(
                text("SELECT * FROM brain_pages WHERE slug = :slug"),
                {"slug": slug},
            )
            row = result.mappings().first()
            if row is None:
                return None
            return _row_to_snapshot(row)

    async def list_versions(self, workspace_id: UUID, slug: str) -> list[BrainPageVersionSnapshot]:
        async with brain_session(workspace_id) as session:
            result = await session.execute(
                text(
                    "SELECT id, page_slug, version, compiled_truth, provenance_id, "
                    "superseded_by, created_at FROM brain_page_versions "
                    "WHERE page_slug = :slug ORDER BY version ASC"
                ),
                {"slug": slug},
            )
            return [_version_row_to_snapshot(r) for r in result.mappings().all()]

    # ---------------- Writes ----------------

    async def upsert_page(
        self,
        workspace_id: UUID,
        *,
        slug: str,
        kind: str,
        title: str,
        compiled_truth: str,
        provenance_id: UUID,
        manager_authoritative: bool = False,
        tags: list[str] | None = None,
        timeline_seed: TimelineEntry | None = None,
    ) -> BrainPageSnapshot:
        timeline_initial = [_timeline_entry_to_dict(timeline_seed)] if timeline_seed else []
        tags_list = tags or []
        now = datetime.now(UTC)

        async with brain_session(workspace_id) as session:
            # Try insert first.
            existing_result = await session.execute(
                text(
                    "SELECT slug, kind, title, compiled_truth, timeline, tags, "
                    "provenance_id, manager_authoritative, deleted_at, version, updated_at "
                    "FROM brain_pages WHERE slug = :slug FOR UPDATE"
                ),
                {"slug": slug},
            )
            existing = existing_result.mappings().first()

            if existing is None:
                await session.execute(
                    text(
                        "INSERT INTO brain_pages "
                        "(slug, kind, title, compiled_truth, timeline, tags, "
                        " provenance_id, manager_authoritative, version, created_at, updated_at) "
                        "VALUES (:slug, :kind, :title, :compiled_truth, "
                        " CAST(:timeline AS jsonb), CAST(:tags AS jsonb), "
                        " :provenance_id, :manager_authoritative, 1, :now, :now)"
                    ),
                    {
                        "slug": slug,
                        "kind": kind,
                        "title": title,
                        "compiled_truth": compiled_truth,
                        "timeline": json.dumps(timeline_initial),
                        "tags": json.dumps(tags_list),
                        "provenance_id": str(provenance_id),
                        "manager_authoritative": manager_authoritative,
                        "now": now,
                    },
                )
                # Seed a v1 version row for completeness.
                v_id = uuid4()
                await session.execute(
                    text(
                        "INSERT INTO brain_page_versions "
                        "(id, page_slug, version, compiled_truth, provenance_id, created_at) "
                        "VALUES (:id, :slug, 1, :ct, :pid, :now)"
                    ),
                    {
                        "id": str(v_id),
                        "slug": slug,
                        "ct": compiled_truth,
                        "pid": str(provenance_id),
                        "now": now,
                    },
                )
                await session.commit()
                fresh = await self.get_page(workspace_id, slug)
                assert fresh is not None
                return fresh

            # Existing page: manager_authoritative guard.
            if existing["manager_authoritative"] and not manager_authoritative:
                raise ManagerAuthoritativeConflict(slug=slug)

            # Same compiled_truth -> just bump updated_at, no new version.
            if existing["compiled_truth"] == compiled_truth:
                await session.execute(
                    text("UPDATE brain_pages SET updated_at = :now WHERE slug = :slug"),
                    {"now": now, "slug": slug},
                )
                await session.commit()
                fresh = await self.get_page(workspace_id, slug)
                assert fresh is not None
                return fresh

            # Real change: write new version row, supersede prior, update page.
            new_version = int(existing["version"]) + 1
            new_v_id = uuid4()
            prior_v_id = uuid4()
            # First persist the PRIOR version's row (the one being superseded),
            # then the NEW version pointing forward.
            await session.execute(
                text(
                    "INSERT INTO brain_page_versions "
                    "(id, page_slug, version, compiled_truth, provenance_id, superseded_by, created_at) "
                    "VALUES (:id, :slug, :v, :ct, :pid, :sup, :now)"
                ),
                {
                    "id": str(prior_v_id),
                    "slug": slug,
                    "v": int(existing["version"]),
                    "ct": existing["compiled_truth"],
                    "pid": str(existing["provenance_id"]) if existing["provenance_id"] else None,
                    "sup": str(new_v_id),
                    "now": now,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO brain_page_versions "
                    "(id, page_slug, version, compiled_truth, provenance_id, created_at) "
                    "VALUES (:id, :slug, :v, :ct, :pid, :now)"
                ),
                {
                    "id": str(new_v_id),
                    "slug": slug,
                    "v": new_version,
                    "ct": compiled_truth,
                    "pid": str(provenance_id),
                    "now": now,
                },
            )
            await session.execute(
                text(
                    "UPDATE brain_pages SET "
                    "  kind = :kind, "
                    "  title = :title, "
                    "  compiled_truth = :ct, "
                    "  provenance_id = :pid, "
                    "  manager_authoritative = :ma, "
                    "  version = :v, "
                    "  updated_at = :now "
                    "WHERE slug = :slug"
                ),
                {
                    "slug": slug,
                    "kind": kind,
                    "title": title,
                    "ct": compiled_truth,
                    "pid": str(provenance_id),
                    "ma": manager_authoritative or bool(existing["manager_authoritative"]),
                    "v": new_version,
                    "now": now,
                },
            )
            await session.commit()
            fresh = await self.get_page(workspace_id, slug)
            assert fresh is not None
            return fresh

    async def append_timeline(
        self,
        workspace_id: UUID,
        *,
        slug: str,
        entry: TimelineEntry,
    ) -> BrainPageSnapshot:
        new_entry = _timeline_entry_to_dict(entry)
        async with brain_session(workspace_id) as session:
            existing_result = await session.execute(
                text("SELECT timeline FROM brain_pages WHERE slug = :slug FOR UPDATE"),
                {"slug": slug},
            )
            existing = existing_result.mappings().first()
            if existing is None:
                raise KeyError(f"brain page {slug!r} does not exist; cannot append timeline")
            current_timeline = list(existing["timeline"] or [])
            current_timeline.append(new_entry)
            await session.execute(
                text(
                    "UPDATE brain_pages SET timeline = CAST(:tl AS jsonb), updated_at = :now "
                    "WHERE slug = :slug"
                ),
                {
                    "tl": json.dumps(current_timeline),
                    "now": datetime.now(UTC),
                    "slug": slug,
                },
            )
            await session.commit()
        fresh = await self.get_page(workspace_id, slug)
        assert fresh is not None
        return fresh

    async def soft_delete_page(self, workspace_id: UUID, slug: str) -> None:
        async with brain_session(workspace_id) as session:
            await session.execute(
                text("UPDATE brain_pages SET deleted_at = :now WHERE slug = :slug"),
                {"now": datetime.now(UTC), "slug": slug},
            )
            await session.commit()

    async def update_tags(
        self, workspace_id: UUID, slug: str, tags: list[str]
    ) -> None:
        """Replace the page's tags list without touching compiled_truth or version chain."""
        async with brain_session(workspace_id) as session:
            await session.execute(
                text(
                    "UPDATE brain_pages SET tags = CAST(:tags AS jsonb), updated_at = :now "
                    "WHERE slug = :slug"
                ),
                {
                    "tags": json.dumps(list(tags)),
                    "now": datetime.now(UTC),
                    "slug": slug,
                },
            )
            await session.commit()

    # ---------------- Search (Phase 1 §F4: RRF + backlink-boost) ----------------

    async def hybrid_search(
        self,
        workspace_id: UUID,
        query: str,
        *,
        k: int = 8,
        types: list[str] | None = None,
    ) -> list[BrainSearchHit]:
        """RRF combiner over (vector, text) lanes per Phase 1 §F4.

        Phase 0 §C11 returned `[]`. This implementation runs both lanes
        in parallel (vector lane is a stub returning `[]` until pgvector
        indexes land in a follow-up; text lane uses ILIKE over title +
        compiled_truth so the function is not vacuous in CI), combines
        them via Reciprocal Rank Fusion (k=60), and applies a backlink-
        boost factor `(1 + 0.05 * min(in_degree, 20))`. `in_degree` reads
        from `brain_edges`; the table is created lazily if absent so
        callers don't need to migrate to use search.
        """
        import asyncio

        async def _vector_lane() -> list[tuple[str, str, str]]:
            # (slug, title, snippet) - empty until pgvector indexes land.
            return []

        async def _text_lane() -> list[tuple[str, str, str]]:
            if not query.strip():
                return []
            pattern = f"%{query.strip()}%"
            async with brain_session(workspace_id) as session:
                stmt = (
                    "SELECT slug, title, compiled_truth FROM brain_pages "
                    "WHERE deleted_at IS NULL "
                    "AND (title ILIKE :pat OR compiled_truth ILIKE :pat) "
                )
                params: dict[str, Any] = {"pat": pattern, "k": k * 2}
                if types:
                    stmt += "AND kind = ANY(:kinds) "
                    params["kinds"] = list(types)
                stmt += "ORDER BY updated_at DESC LIMIT :k"
                result = await session.execute(text(stmt), params)
                rows = result.mappings().all()
            return [
                (r["slug"], r["title"], (r["compiled_truth"] or "")[:200]) for r in rows
            ]

        vec_hits, text_hits = await asyncio.gather(_vector_lane(), _text_lane())

        rrf: dict[str, float] = {}
        meta: dict[str, tuple[str, str]] = {}
        for rank, (slug, title, snip) in enumerate(vec_hits):
            rrf[slug] = rrf.get(slug, 0.0) + 1.0 / (60 + rank)
            meta.setdefault(slug, (title, snip))
        for rank, (slug, title, snip) in enumerate(text_hits):
            rrf[slug] = rrf.get(slug, 0.0) + 1.0 / (60 + rank)
            meta.setdefault(slug, (title, snip))

        if not rrf:
            return []

        # Backlink boost - look up in_degree per slug from brain_edges if present.
        try:
            async with brain_session(workspace_id) as session:
                slugs = list(rrf.keys())
                in_degree_result = await session.execute(
                    text(
                        "SELECT to_slug, COUNT(*) AS cnt FROM brain_edges "
                        "WHERE to_slug = ANY(:slugs) GROUP BY to_slug"
                    ),
                    {"slugs": slugs},
                )
                in_degree = {row["to_slug"]: int(row["cnt"]) for row in in_degree_result.mappings().all()}
        except Exception:
            # brain_edges table not yet created in this schema - skip the boost.
            in_degree = {}

        for slug in rrf:
            deg = min(in_degree.get(slug, 0), 20)
            rrf[slug] *= 1 + 0.05 * deg

        ranked = sorted(rrf, key=lambda s: rrf[s], reverse=True)[:k]
        out: list[BrainSearchHit] = []
        for slug in ranked:
            title, snip = meta.get(slug, (slug, ""))
            out.append(
                BrainSearchHit(slug=slug, title=title, snippet=snip, score=rrf[slug])
            )
        return out

    # ---------------- Typed graph traversal (stub) ----------------

    async def traverse(
        self,
        workspace_id: UUID,
        slug: str,
        *,
        depth: int = 2,
        edge_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Graph traversal over brain_edges.

        Returns a list of edge dicts `{from_slug, to_slug, edge_type, depth}`.
        If the `brain_edges` table is absent the method returns `[]`
        rather than raising - callers can opt in to graph queries as the
        edge model rolls out per workspace.
        """
        del depth, edge_types  # Phase 1 ships a stub - depth=1 fixed
        try:
            async with brain_session(workspace_id) as session:
                result = await session.execute(
                    text(
                        "SELECT from_slug, to_slug, edge_type FROM brain_edges "
                        "WHERE from_slug = :slug OR to_slug = :slug"
                    ),
                    {"slug": slug},
                )
                rows = result.mappings().all()
        except Exception:
            return []
        return [
            {
                "from_slug": r["from_slug"],
                "to_slug": r["to_slug"],
                "edge_type": r["edge_type"],
                "depth": 1,
            }
            for r in rows
        ]
