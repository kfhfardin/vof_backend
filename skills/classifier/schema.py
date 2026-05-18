"""Classifier skill - Input + Output Pydantic schemas.

Both class names (`Input`, `Output`) are loader convention.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Scope = Literal["ORG_WIDE", "CALLER_SPECIFIC", "BOTH", "RAW_SOURCE"]
Kind = Literal[
    "account",
    "person",
    "product",
    "playbook",
    "theme",
    "caller_identity",
    "caller_style",
    "raw_document",
    "org_positioning",
    "off_topic",
]


class RosterEntry(BaseModel):
    id: UUID
    name: str
    role: str | None = None


class AccountRef(BaseModel):
    slug: str
    title: str


class Input(BaseModel):
    workspace_id: UUID
    workspace_name: str
    content: str = Field(min_length=1, max_length=200_000)
    source: str = "form"  # form | upload | voice_intake | correction
    filename: str | None = None
    roster: list[RosterEntry] = Field(default_factory=list)
    known_accounts: list[AccountRef] = Field(default_factory=list)


class ExtractedEntity(BaseModel):
    type: Literal["person", "company", "product", "theme"]
    name: str


class Output(BaseModel):
    scope: Scope
    kind: Kind
    target_caller_id: UUID | None = None
    suggested_slug: str | None = None
    extracted_entities: list[ExtractedEntity] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
