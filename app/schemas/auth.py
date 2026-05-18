"""Auth + signup DTOs."""

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)
    workspace_name: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class WorkspaceSummary(BaseModel):
    id: UUID
    name: str
    primary_number: str | None
    provisioning_state: str


class UserSummary(BaseModel):
    id: UUID
    email: EmailStr
    role: str
    organization_id: UUID
    workspace_id: UUID | None


class SignupResponse(BaseModel):
    user: UserSummary
    workspace: WorkspaceSummary
    tokens: TokenPair


class MeResponse(BaseModel):
    user: UserSummary
    workspace: WorkspaceSummary | None
