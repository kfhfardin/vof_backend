"""Intake DTOs."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class IntakeTextSubmission(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    purpose: Literal["onboarding", "ongoing_update", "correction"] = "ongoing_update"


class IntakeItemSummary(BaseModel):
    id: UUID
    workspace_id: UUID
    source: str
    purpose: str
    status: str
    extractor_used: str | None
    content_filename: str | None
    content_mime: str | None
    content_sha256: str | None
    classification: dict[str, Any] | None
    handler_result: dict[str, Any] | None
    superseded_by_item_id: UUID | None
    error: str | None
    created_at: datetime


class IntakeUploadResponse(BaseModel):
    item: IntakeItemSummary
    deduped: bool = False


class IntakeListResponse(BaseModel):
    items: list[IntakeItemSummary]
    limit: int
    offset: int


class IntakeSupersedeRequest(BaseModel):
    new_item_id: UUID


class IntakeReviewSummary(BaseModel):
    total_recent: int
    by_status: dict[str, int]
    by_kind: dict[str, int]
    needs_review_count: int
    ingested_count: int
    failed_count: int


class IntakeReviewResponse(BaseModel):
    summary: IntakeReviewSummary
    needs_review: list[IntakeItemSummary]
