"""Password hashing (bcrypt — modern direct binding).

bcrypt has a 72-byte hard limit on the input. We hash with a leading
SHA-256 round to remove the limit, which is the standard mitigation.
This is compatible with itself (verify rebuilds the same digest).
"""

import hashlib
import hmac
import os

import bcrypt

# Application-wide pepper - tied to the bcrypt prehash, not the JWT secret.
# Empty by default; set BCRYPT_PEPPER if you want it mixed in.
_PEPPER = os.environ.get("BCRYPT_PEPPER", "").encode()


def _prehash(plain: str) -> bytes:
    """SHA-256 the password so we never hit bcrypt's 72-byte limit."""
    digest = hmac.new(_PEPPER, plain.encode("utf-8"), hashlib.sha256).digest()
    return digest


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_prehash(plain), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(plain), hashed.encode("utf-8"))
    except ValueError:
        return False
