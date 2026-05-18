"""JWT encode/decode + claim shape."""

import uuid

import pytest

from app.security.jwt import InvalidToken, decode_token, encode_token


def test_roundtrip() -> None:
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    token, jti, _exp = encode_token(
        user_id=user_id,
        organization_id=org_id,
        workspace_id=ws_id,
        role="manager",
        token_type="access",
    )
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == str(user_id)
    assert payload["org"] == str(org_id)
    assert payload["ws"] == str(ws_id)
    assert payload["role"] == "manager"
    assert payload["jti"] == jti
    assert payload["type"] == "access"


def test_workspace_id_null_for_org_admin() -> None:
    token, _, _ = encode_token(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        workspace_id=None,
        role="org_admin",
        token_type="access",
    )
    payload = decode_token(token)
    assert payload["ws"] is None


def test_expected_type_mismatch_rejected() -> None:
    token, _, _ = encode_token(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        workspace_id=None,
        role="manager",
        token_type="refresh",
    )
    with pytest.raises(InvalidToken, match="expected access"):
        decode_token(token, expected_type="access")


def test_tampered_token_rejected() -> None:
    token, _, _ = encode_token(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        workspace_id=None,
        role="manager",
        token_type="access",
    )
    # Mangle the signature segment
    parts = token.split(".")
    tampered = ".".join([parts[0], parts[1], "AAAAAAAA" + parts[2][8:]])
    with pytest.raises(InvalidToken):
        decode_token(tampered)
