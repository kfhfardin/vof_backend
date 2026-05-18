"""WebSocket frame schemas (the contract with the FE).

The Manager opens one WS per session; the server multiplexes all of the
Workspace's active calls onto it. Each frame carries a `type` discriminator
plus a `call_id` so the FE can route to the right call pane.

Per LLD §C5 + HLD §5.5.2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class CallStartedFrame(BaseModel):
    type: Literal["call.started"] = "call.started"
    call_id: UUID
    field_employee_id: UUID | None
    started_at: datetime


class TranscriptFragmentFrame(BaseModel):
    type: Literal["transcript.fragment"] = "transcript.fragment"
    call_id: UUID
    speaker: Literal["caller", "agent"]
    text: str
    seq: int
    ts: datetime


class DecisionOpenedFrame(BaseModel):
    """Populated by §C6 when the Orchestrator opens a decision request."""

    type: Literal["decision.opened"] = "decision.opened"
    call_id: UUID
    decision_id: UUID
    prompt: str
    options: list[str]
    decision_class: Literal["inline", "bridged", "async"]
    timeout_at: datetime | None


class DecisionResolvedFrame(BaseModel):
    """Populated by §C6 / §C7 when a decision is answered or times out."""

    type: Literal["decision.resolved"] = "decision.resolved"
    call_id: UUID
    decision_id: UUID
    response: str | None
    responded_via: Literal["websocket", "sms", "timeout"]


class CallEndedFrame(BaseModel):
    type: Literal["call.ended"] = "call.ended"
    call_id: UUID
    ended_at: datetime


class CallSummaryReadyFrame(BaseModel):
    """Pushed by the post_call worker once summarization + writeback finish.
    The FE re-fetches the call summary endpoint when it sees this."""

    type: Literal["call.summary_ready"] = "call.summary_ready"
    call_id: UUID
    has_summary: bool
    brain_pages_touched: list[str]


class SnapshotFrame(BaseModel):
    """First frame sent after WS connect - the in-progress call list."""

    type: Literal["snapshot"] = "snapshot"
    calls: list[CallStartedFrame]


class PingFrame(BaseModel):
    """Server-side heartbeat. The FE may echo back as `pong` (client-driven)
    or just ignore; the server uses Starlette's protocol ping concurrently.
    """

    type: Literal["ping"] = "ping"
    ts: datetime


Frame = (
    CallStartedFrame
    | TranscriptFragmentFrame
    | DecisionOpenedFrame
    | DecisionResolvedFrame
    | CallEndedFrame
    | CallSummaryReadyFrame
    | SnapshotFrame
    | PingFrame
)
