"""Supermemory probe.

Verifies the exact SDK surface the production adapter uses
(app/memory/supermemory.py):

  - AsyncSupermemory client (same as production)
  - add(content, container_tags, metadata)
  - search.documents(q, container_tags, limit)   # the documented method
  - profile(container_tag=...)                   # callable on client
  - memories.forget(container_tag, id)           # delete equivalent

The per-caller isolation check is the load-bearing assertion: a memory
written under one caller's tag MUST NOT appear in another caller's
search. If the SDK silently changes semantics (e.g. AND-matching to
OR-matching tags), this probe catches it before prod.

See LLD section B3.
"""

import asyncio
import os
import uuid
from typing import Any, ClassVar

from smoke._base import CheckResult, Probe, UpstreamUnavailable, main_for


def _caller_tag(field_employee_id: uuid.UUID) -> str:
    return f"caller_{field_employee_id}"


def _workspace_tag(workspace_id: uuid.UUID) -> str:
    return f"workspace_{workspace_id}"


def _container_tags(workspace_id: uuid.UUID, field_employee_id: uuid.UUID) -> list[str]:
    return [_caller_tag(field_employee_id), _workspace_tag(workspace_id)]


class SupermemoryProbe(Probe):
    name: ClassVar[str] = "supermemory"
    required_env: ClassVar[list[str]] = ["SUPERMEMORY_API_KEY"]

    def checks_for_mode(self) -> None:
        try:
            self._checks_for_mode_impl()
        finally:
            self._close_runner()

    def _checks_for_mode_impl(self) -> None:
        self.check(
            "auth_valid",
            self._auth_valid,
            fix_hint="Regenerate the API key in the Supermemory dashboard.",
        )

        if self.mode not in ("smoke", "repair"):
            return

        # Synthetic (workspace, two-caller) trio for the isolation check.
        smoke_ws = uuid.uuid4()
        smoke_caller_a = uuid.uuid4()
        smoke_caller_b = uuid.uuid4()
        memory_ids: list[tuple[str, str]] = []  # (container_tag, memory_id) for cleanup

        try:
            mid_a = self._run(
                self._write(
                    container_tags=_container_tags(smoke_ws, smoke_caller_a),
                    content="smoketest caller-A content " + uuid.uuid4().hex,
                )
            )
            self.report.checks.append(CheckResult("memory_write_caller_a", True, 0.0, f"id={mid_a}"))
            memory_ids.append((_caller_tag(smoke_caller_a), mid_a))

            mid_b = self._run(
                self._write(
                    container_tags=_container_tags(smoke_ws, smoke_caller_b),
                    content="smoketest caller-B content " + uuid.uuid4().hex,
                )
            )
            self.report.checks.append(CheckResult("memory_write_caller_b", True, 0.0, f"id={mid_b}"))
            memory_ids.append((_caller_tag(smoke_caller_b), mid_b))

            # Per-turn retrieval uses the SINGLE caller tag (not [caller, workspace])
            # because Supermemory's container_tags is OR-matching, not AND. The
            # single-tag search is the only safe per-caller isolation path; see
            # app/orchestrator/retrieval.py:for_turn for the matching production code.
            self.check(
                "caller_a_finds_own_memory",
                lambda: self._run(
                    self._search_finds([_caller_tag(smoke_caller_a)], mid_a, "smoketest")
                ),
                fix_hint="Indexing lag > 30s, or container_tags filter not honored.",
            )
            self.check(
                "caller_b_finds_own_memory",
                lambda: self._run(
                    self._search_finds([_caller_tag(smoke_caller_b)], mid_b, "smoketest")
                ),
            )
            self.check(
                "caller_a_does_not_see_caller_b_memory",
                lambda: self._run(
                    self._search_excludes(
                        container_tags=[_caller_tag(smoke_caller_a)],
                        excluded_id=mid_b,
                        query="smoketest",
                        sentinel_id=mid_a,
                    )
                ),
                fix_hint=(
                    "ISOLATION FAILURE: single-tag caller search returned another caller's memory. "
                    "This is the production retrieval path (Retriever.for_turn searches with "
                    "[caller_tag] only). If this fails, per-caller isolation is broken."
                ),
            )
            # Belt-and-braces: confirm the OR-match assumption — a search with
            # BOTH caller_a and workspace tags should return memories from BOTH
            # callers (because OR semantics + shared workspace tag), which is
            # exactly why production retrieval avoids the two-tag pattern.
            self.check(
                "container_tags_or_semantics_documented",
                lambda: self._run(
                    self._asserts_or_semantics(
                        smoke_ws, smoke_caller_a, smoke_caller_b, mid_a, mid_b
                    )
                ),
                fix_hint=(
                    "If this check now PASSES with isolation (only mid_a returned), "
                    "Supermemory changed container_tags to AND-matching. Revisit "
                    "Retriever.for_turn — the workaround is no longer needed."
                ),
            )
            self.check(
                "workspace_tag_finds_both",
                lambda: self._run(
                    self._search_finds_all([_workspace_tag(smoke_ws)], {mid_a, mid_b}, "smoketest")
                ),
                fix_hint="The workspace tag should match both caller writes.",
            )
            # profile() is the same call site Retriever.prewarm_starter uses
            # on call-start. Generation is async on SM's side - an empty
            # profile is acceptable for a fresh tag.
            self.check(
                "profile_endpoint_reachable",
                lambda: self._run(self._profile_reachable(_caller_tag(smoke_caller_a))),
                fix_hint=(
                    "client.profile() failed - this is the call site the "
                    "orchestrator uses on call-start prewarm."
                ),
            )
        finally:
            for tag, mid in memory_ids:
                try:
                    self._run(self._forget(tag, mid))
                except Exception:
                    pass

    # ---------------- async helpers ----------------

    _runner: asyncio.Runner | None = None
    _client_cache: Any = None  # AsyncSupermemory — cached per probe run

    def _run(self, coro: Any) -> Any:
        """Run an async coroutine on the probe's shared event loop.

        We share ONE asyncio.Runner across all checks so the loop stays
        alive long enough for httpx's connection-pool cleanup tasks to
        complete. The earlier `asyncio.run()` per-check pattern closed
        the loop immediately, stranding those cleanups and producing
        `RuntimeError: Event loop is closed` noise on stderr.
        """
        if self._runner is None:
            self._runner = asyncio.Runner()
        return self._runner.run(coro)

    def _close_runner(self) -> None:
        """Close the shared AsyncSupermemory client + the asyncio loop.

        Order matters: close the SDK client (which closes its httpx pool)
        FIRST, while the loop is still running, then close the loop.
        """
        if self._runner is not None and self._client_cache is not None:
            try:
                self._runner.run(self._aclose_client())
            except Exception:
                pass
            self._client_cache = None
        if self._runner is not None:
            try:
                self._runner.close()
            except Exception:
                pass
            self._runner = None

    async def _aclose_client(self) -> None:
        if self._client_cache is not None:
            close = getattr(self._client_cache, "aclose", None) or getattr(self._client_cache, "close", None)
            if close is not None:
                await close()

    def _async_client(self):  # type: ignore[no-untyped-def]
        """Return the cached AsyncSupermemory client (one per probe run)."""
        if self._client_cache is None:
            from supermemory import AsyncSupermemory

            self._client_cache = AsyncSupermemory(api_key=os.environ["SUPERMEMORY_API_KEY"])
        return self._client_cache

    async def _do_auth_check(self) -> None:
        client = self._async_client()
        await client.search.documents(q="ping", limit=1)

    def _auth_valid(self) -> str:
        try:
            self._run(self._do_auth_check())
            return "auth ok"
        except Exception as e:
            msg = str(e)
            if "401" in msg or "Unauthorized" in msg or "auth" in msg.lower():
                raise RuntimeError("API key rejected") from e
            if msg[:3].startswith("5"):
                raise UpstreamUnavailable(msg) from e
            raise

    async def _write(self, *, container_tags: list[str], content: str) -> str:
        client = self._async_client()
        result = await client.add(
            content=content,
            container_tags=container_tags,
            metadata={"smoketest": "true"},
        )
        mid = getattr(result, "id", None) or (result.get("id") if isinstance(result, dict) else None)
        if not mid:
            raise RuntimeError(f"no memory id returned: {result!r}")
        return str(mid)

    async def _search_raw(self, container_tags: list[str], query: str, *, limit: int = 10) -> list[Any]:
        client = self._async_client()
        r = await client.search.documents(q=query, container_tags=container_tags, limit=limit)
        results = getattr(r, "results", None) or (r.get("results") if isinstance(r, dict) else None) or []
        return list(results)

    def _ids_from(self, items: list[Any]) -> set[str]:
        """Pull the memory id from search-result items.

        Supermemory's SearchDocumentsResponse exposes the id as `document_id`
        (or its camelCase alias `documentId`) on each result — NOT `id`. The
        previous `id` lookup silently returned "" on every search result, so
        every find-check failed not because indexing was slow but because we
        weren't recognizing the matches.
        """
        out: set[str] = set()
        for m in items:
            mid = ""
            for attr in ("document_id", "documentId", "id"):
                val = getattr(m, attr, None)
                if val:
                    mid = str(val)
                    break
            if not mid and isinstance(m, dict):
                for key in ("document_id", "documentId", "id"):
                    val = m.get(key)
                    if val:
                        mid = str(val)
                        break
            if mid:
                out.add(mid)
        return out

    # Supermemory indexes writes asynchronously: empirically ~5s for one tag,
    # ~10s for two tags. Poll up to 30s with 2s intervals so freshly-written
    # memories under the production [caller_<uuid>, workspace_<uuid>] pattern
    # have time to become searchable.
    _POLL_ATTEMPTS = 15
    _POLL_INTERVAL_S = 2

    async def _search_finds(self, container_tags: list[str], memory_id: str, query: str) -> str:
        for attempt in range(self._POLL_ATTEMPTS):
            ids = self._ids_from(await self._search_raw(container_tags, query))
            if memory_id in ids:
                return f"found in {attempt + 1} attempt(s)"
            await asyncio.sleep(self._POLL_INTERVAL_S)
        raise RuntimeError(
            f"memory {memory_id[:8]}... not in {container_tags} search after "
            f"{self._POLL_ATTEMPTS * self._POLL_INTERVAL_S}s"
        )

    async def _search_excludes(
        self,
        container_tags: list[str],
        excluded_id: str,
        query: str,
        sentinel_id: str,
    ) -> str:
        """Assert excluded_id is NOT visible under container_tags.

        Waits for indexing to actually complete on this tag (by polling for a
        sentinel_id we know IS under it) before asserting the exclusion.
        Otherwise an empty-result-set (indexing not done yet) would trivially
        "pass" the isolation check for the wrong reason.
        """
        for attempt in range(self._POLL_ATTEMPTS):
            ids = self._ids_from(await self._search_raw(container_tags, query))
            if sentinel_id in ids:
                # Tag is now indexed - the absence of excluded_id is meaningful.
                if excluded_id in ids:
                    raise RuntimeError(
                        f"isolation broken: memory {excluded_id[:8]}... visible under "
                        f"foreign tags {container_tags}"
                    )
                return f"sentinel found ({len(ids)} ids), excluded not present"
            await asyncio.sleep(self._POLL_INTERVAL_S)
        raise RuntimeError(
            f"sentinel {sentinel_id[:8]}... did not become searchable on its own tag "
            f"after {self._POLL_ATTEMPTS * self._POLL_INTERVAL_S}s; cannot verify isolation"
        )

    async def _search_finds_all(self, container_tags: list[str], expected_ids: set[str], query: str) -> str:
        for attempt in range(self._POLL_ATTEMPTS):
            ids = self._ids_from(await self._search_raw(container_tags, query, limit=50))
            if expected_ids.issubset(ids):
                return f"all {len(expected_ids)} found in {attempt + 1} attempt(s)"
            await asyncio.sleep(self._POLL_INTERVAL_S)
        raise RuntimeError(
            f"workspace tag did not return all expected memories after "
            f"{self._POLL_ATTEMPTS * self._POLL_INTERVAL_S}s: expected={expected_ids}"
        )

    async def _asserts_or_semantics(
        self,
        ws: uuid.UUID,
        caller_a: uuid.UUID,
        caller_b: uuid.UUID,
        mid_a: str,
        mid_b: str,
    ) -> str:
        """Verify Supermemory still uses OR-matching on container_tags.

        If this assertion no longer holds (i.e. Supermemory switches to AND),
        Retriever.for_turn could safely go back to the two-tag pattern.
        Until then, this check is a tripwire to alert us to that change.
        """
        for _ in range(self._POLL_ATTEMPTS):
            ids = self._ids_from(
                await self._search_raw(
                    [_caller_tag(caller_a), _workspace_tag(ws)],
                    "smoketest",
                )
            )
            if mid_a in ids and mid_b in ids:
                return "confirmed OR-matching (both ids returned for [caller_a, workspace])"
            if mid_a in ids and mid_b not in ids:
                raise RuntimeError(
                    "container_tags now appears AND-matching — Retriever.for_turn "
                    "can be simplified to the [caller, workspace] pattern again"
                )
            await asyncio.sleep(self._POLL_INTERVAL_S)
        raise RuntimeError("could not determine semantic — neither memory visible after polling")

    async def _profile_reachable(self, container_tag: str) -> str:
        client = self._async_client()
        # client.profile is a callable, NOT client.profile.get - if the SDK
        # ever switches to a sub-resource shape this will fail loudly.
        try:
            response = await client.profile(container_tag=container_tag)
        except AttributeError as e:
            raise RuntimeError(f"client.profile() shape changed: {e}") from e
        if response is None:
            return "profile endpoint returned None (acceptable for new tag)"
        return f"profile OK (type={type(response).__name__})"

    async def _forget(self, container_tag: str, memory_id: str) -> None:
        client = self._async_client()
        # No client.memories.delete in the SDK; forget IS the delete and
        # requires container_tag.
        await client.memories.forget(container_tag=container_tag, id=memory_id)


if __name__ == "__main__":
    raise SystemExit(main_for(SupermemoryProbe))
