"""Settings validation rules."""

import pytest
from pydantic import ValidationError

from app.settings import Settings


def test_settings_loads_from_env() -> None:
    s = Settings()  # type: ignore[call-arg]
    assert s.deployment_profile in ("local", "cloud")
    assert s.environment in ("dev", "staging", "prod")


def test_jwt_secret_must_be_long_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "too-short")
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings()  # type: ignore[call-arg]


def test_local_profile_requires_s3_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("S3_ENDPOINT_URL", "")
    with pytest.raises(ValidationError, match="S3_ENDPOINT_URL"):
        Settings()  # type: ignore[call-arg]


def test_secret_str_not_in_repr() -> None:
    s = Settings()  # type: ignore[call-arg]
    rep = repr(s)
    # SecretStr fields should never leak via repr; pydantic shows them as **********.
    assert s.jwt_secret.get_secret_value() not in rep
