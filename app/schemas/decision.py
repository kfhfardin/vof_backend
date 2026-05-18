"""Decision DTOs."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class DecisionSummary(BaseModel):
    id: UUID
    call_id: UUID
    workspace_id: UUID
    prompt: str
    options: list[str]
    decision_class: str
    status: str
    timeout_at: datetime | None
    response: str | None
    responded_at: datetime | None
    responded_via: str | None
    context: dict[str, Any] | None
    created_at: datetime


class DecisionListResponse(BaseModel):
    decisions: list[DecisionSummary]
    limit: int
    offset: int


class DecisionRespondRequest(BaseModel):
    response: str
    via: Literal["websocket"] = "websocket"
