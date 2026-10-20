# -*- coding: utf-8 -*-
"""Password hashing (stdlib scrypt) and JWT issue/verify.

Hashing uses hashlib.scrypt so there is no crypto dependency beyond
PyJWT. The login flow itself is a dev bootstrap: bank SSO/LDAP replaces
it later (architecture.md §13 decision), at which point password
columns can be dropped or kept as fallback.
"""
import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings

_SCRYPT_PARAMS = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    """Hash *password* as ``scrypt$<salt b64>$<digest b64>``."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, dklen=32, **_SCRYPT_PARAMS
    )
    return "scrypt${}${}".format(
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of *password* against a stored scrypt hash."""
    try:
        scheme, salt_b64, digest_b64 = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(digest_b64)
    actual = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        dklen=len(expected),
        **_SCRYPT_PARAMS,
    )
    return hmac.compare_digest(actual, expected)


def create_access_token(user_id: int, username: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """Raise :class:`jwt.PyJWTError` on invalid/expired tokens."""
    return jwt.decode(
        token, get_settings().jwt_secret, algorithms=["HS256"]
    )
