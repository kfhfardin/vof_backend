"""Brain DTOs."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class BrainPageView(BaseModel):
    slug: str
    kind: str
    title: str
    compiled_truth: str
    timeline: list[dict[str, Any]]
    tags: list[str]
    provenance_id: UUID | None
    manager_authoritative: bool
    deleted_at: datetime | None
    version: int
    updated_at: datetime


class BrainPageVersionView(BaseModel):
    id: UUID
    slug: str
    version: int
    compiled_truth: str
    provenance_id: UUID | None
    superseded_by: UUID | None
    created_at: datetime


class BrainPageVersionsResponse(BaseModel):
    slug: str
    versions: list[BrainPageVersionView]


class CorrectionRequest(BaseModel):
    target_slug: str = Field(min_length=1, max_length=200)
    kind: Literal["replace_compiled_truth", "soft_delete_page", "append_timeline_entry"]
    payload: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None = None
