"""Password hashing primitives."""

from app.security.hashing import hash_password, verify_password


def test_roundtrip() -> None:
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong password", h)


def test_hash_is_deterministic_in_verify_not_in_hash() -> None:
    # bcrypt salts the hash, so two hashes of the same plaintext differ.
    a = hash_password("same")
    b = hash_password("same")
    assert a != b
    # Both verify the original plaintext correctly.
    assert verify_password("same", a)
    assert verify_password("same", b)
