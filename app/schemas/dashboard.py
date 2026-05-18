"""Dashboard request/response DTOs - Phase 1 §F8."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------- Daily brief ----------------


class DailyBriefResponse(BaseModel):
    brief_id: UUID
    workspace_id: UUID
    brief_date: date
    subject_line: str | None = None
    sections: dict[str, Any] = Field(default_factory=dict)
    missed_decision_ids: list[str] = Field(default_factory=list)
    computed_at: datetime


# ---------------- Resolve-now ----------------


class ResolveNowRequest(BaseModel):
    option: str


# ---------------- Generic snapshot wrapper ----------------


class SnapshotResponse(BaseModel):
    snapshot_date: date
    dimension: str
    key: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    computed_at: datetime


class SnapshotListResponse(BaseModel):
    workspace_id: UUID
    dimension: str
    date_from: date
    date_to: date
    snapshots: list[SnapshotResponse]


# ---------------- Overview (direct query) ----------------


class OverviewResponse(BaseModel):
    workspace_id: UUID
    as_of: datetime
    today_call_count: int
    in_progress_call_count: int
    decisions_opened_today: int
    decisions_open_now: int


# ---------------- Saved queries ----------------


class CreateSavedQueryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    dimension: str = Field(min_length=1, max_length=32)
    filters: dict[str, Any] = Field(default_factory=dict)
    pinned: bool = False


class SavedQueryResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    user_id: UUID
    name: str
    dimension: str
    filters: dict[str, Any]
    pinned: bool
    created_at: datetime
    updated_at: datetime


class SavedQueryListResponse(BaseModel):
    queries: list[SavedQueryResponse]
