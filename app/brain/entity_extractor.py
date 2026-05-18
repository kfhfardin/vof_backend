"""Extended regex entity extractor (Phase 1 §F4).

Builds on the §C11 summarizer-driven entity flow by surfacing additional
high-signal entity types that don't require an LLM: monetary amounts,
calendar dates, and URLs. Additive: the existing summarizer path still
runs and produces person/account/product/theme entities; this extractor
augments those with concrete data points.

Conservative regex + optional roster cross-reference. The roster check
exists to drop common false-positive "person" matches (e.g. "March"
matching a name pattern). For now we only apply roster on `person`
entities; money/date/url are emitted unconditionally.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_MONEY_RE = re.compile(r"\$\d+(?:,\d{3})*(?:\.\d+)?(?:[KMB])?")
_DATE_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s)>]+")

_SLUG_CHARS = re.compile(r"[^a-z0-9-_]+")


def _slugify(text: str) -> str:
    s = text.strip().lower().replace(" ", "-")
    s = _SLUG_CHARS.sub("", s)
    return s.strip("-") or "untitled"


@dataclass(frozen=True)
class Entity:
    """Matches the summarizer-driven entity shape (type, name, slug_hint)."""

    type: str
    name: str
    slug_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "name": self.name, "slug_hint": self.slug_hint}


def _name_in_roster(name: str, roster: list[dict[str, Any]]) -> bool:
    n = name.strip().lower()
    for entry in roster:
        candidate = str(entry.get("name") or "").strip().lower()
        if candidate and candidate == n:
            return True
    return False


def extract_extended_entities(
    text: str, roster: list[dict[str, Any]] | None = None
) -> list[Entity]:
    """Extract money / date / URL entities from free text.

    When `roster` is supplied, the extractor also emits `person` entities
    for any roster name that appears in the text (case-insensitive).
    Money / date / URL emissions are roster-independent.

    Returns deduplicated entities preserving first-seen order.
    """
    out: list[Entity] = []
    seen: set[tuple[str, str]] = set()

    def _emit(entity: Entity) -> None:
        key = (entity.type, entity.name.strip().lower())
        if key in seen:
            return
        seen.add(key)
        out.append(entity)

    if not text:
        return out

    for m in _MONEY_RE.finditer(text):
        raw = m.group(0)
        _emit(
            Entity(
                type="money",
                name=raw,
                slug_hint=f"money/{_slugify(raw.replace('$', 'usd-'))}",
            )
        )
    for m in _DATE_RE.finditer(text):
        raw = m.group(0)
        _emit(Entity(type="date", name=raw, slug_hint=f"dates/{_slugify(raw)}"))
    for m in _URL_RE.finditer(text):
        raw = m.group(0).rstrip(".,;")
        _emit(Entity(type="url", name=raw, slug_hint=f"urls/{_slugify(raw)}"))

    # Roster cross-reference (only for `person` emissions). Drop persons not in roster.
    if roster:
        text_lower = text.lower()
        for entry in roster:
            cand = str(entry.get("name") or "").strip()
            if not cand:
                continue
            if cand.lower() in text_lower:
                _emit(
                    Entity(
                        type="person",
                        name=cand,
                        slug_hint=f"people/{_slugify(cand)}",
                    )
                )
    # When no roster is provided, we don't emit any person entities here -
    # the summarizer remains the authoritative source for person/account/etc.

    return out


__all__ = ["Entity", "extract_extended_entities"]
