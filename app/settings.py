"""Application configuration.

Single source of truth for runtime settings, sourced from env files + process env.
Validated at startup; failure to validate exits with code 2 (matching smoke-probe
CONFIG semantics).
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Profile ---
    deployment_profile: Literal["local", "cloud"] = "local"
    environment: Literal["dev", "staging", "prod"] = "dev"

    # --- Databases ---
    database_url: str
    brain_database_url: str
    redis_url: str

    # --- Object storage ---
    s3_bucket: str
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = None

    # --- Auth ---
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_seconds: int = 3600
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 30

    # --- Third-party ---
    agentphone_api_key: SecretStr = SecretStr("")
    agentphone_webhook_secret: SecretStr = SecretStr("")
    supermemory_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")

    # --- Phase 1 third-party (F5, F6) ---
    # F9 Google Workspace integration is dormant — the connector + endpoints
    # remain in the codebase but degrade cleanly (503 from endpoints, draft-only
    # output from email/scheduler handlers). To re-enable later, add
    # GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET back here AND set
    # them in env; the existing `is_google_workspace_configured()` helper flips
    # to True automatically.
    agentmail_api_key: SecretStr = SecretStr("")
    email_domain: str | None = None                      # optional custom domain for <slug>@<domain>
    browser_use_api_key: SecretStr = SecretStr("")

    # --- LLM ---
    # Two providers selected by LLM_PROVIDER:
    #   openai_compat (default): any OpenAI-compatible endpoint. Auth via
    #     LLM_API_KEY bearer; base URL from LLM_BASE_URL.
    #   bedrock: AWS Bedrock invoke_model + invoke_model_with_response_stream
    #     via the native Anthropic Messages API. Auth via ANTHROPIC_API_KEY
    #     (the Bedrock long-term API key); surfaced to boto3 as
    #     AWS_BEARER_TOKEN_BEDROCK at client construction. Model IDs must be
    #     cross-region inference profile IDs (e.g. us.anthropic.claude-sonnet-4-6).
    llm_provider: Literal["openai_compat", "bedrock"] = "openai_compat"
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://api.anthropic.com/v1/openai"
    llm_default_model: str = "claude-sonnet-4-6"
    aws_region: str = "us-east-1"

    # --- Public URLs / CORS ---
    public_base_url: str
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # --- Observability ---
    log_level: Literal["DEBUG", "INFO", "WARN", "ERROR"] = "INFO"
    otel_exporter_endpoint: str | None = None

    # --- Validation rules ---
    @model_validator(mode="after")
    def _validate_jwt_secret_length(self) -> "Settings":
        if len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 bytes")
        return self

    @model_validator(mode="after")
    def _validate_local_storage(self) -> "Settings":
        if self.deployment_profile == "local" and not self.s3_endpoint_url:
            raise ValueError("local profile requires S3_ENDPOINT_URL (MinIO/R2)")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton accessor. Never instantiate Settings() elsewhere."""
    return Settings()
