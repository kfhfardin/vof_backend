"""Web Verifier skill - Input + Output Pydantic schemas.

The skill expects the mini-agent to have already fetched ONE page and
pass the resulting text snippet as `evidence_text`. This keeps the
skill single-turn (no tool use), which is the speed-variant design.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ClaimToVerify(BaseModel):
    subject: str                               # entity slug, e.g. "accounts/acme-corp"
    predicate: str                             # e.g. "headquarters_in"
    object: str                                # e.g. "Berlin"
    source_utterance: str                      # verbatim from the call
    scope: Literal["org_wide", "both"]         # caller-specific filtered upstream


class Input(BaseModel):
    workspace_id: UUID
    claim: ClaimToVerify
    evidence_url: str | None = None            # the URL the mini-agent fetched
    evidence_text: str | None = None           # the page text (truncated if huge)
    fetch_ok: bool = True                       # False if the fetch failed; verdict must be unconfirmed


class Output(BaseModel):
    status: Literal["corroborated", "unconfirmed", "contradicted"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_url: str | None = None
    evidence_snippet: str | None = Field(default=None, max_length=1500)
    contradiction_detail: str | None = Field(default=None, max_length=2000)
    reasoning: str = Field(min_length=1, max_length=2000)
