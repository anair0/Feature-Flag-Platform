"""Passwords, session tokens, and SDK keys."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid

import jwt

from app.core.config import settings

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, dk_b64 = stored.split("$")
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


def create_token(user_id: uuid.UUID) -> str:
    now = int(time.time())
    payload = {"sub": str(user_id), "iat": now, "exp": now + settings.jwt_ttl_seconds}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return uuid.UUID(payload["sub"])
    except Exception:
        return None


def new_sdk_key(kind: str) -> str:
    prefix = {"server": "srv-", "client": "cli-"}[kind]
    return prefix + secrets.token_urlsafe(24)


def hash_sdk_key(key: str) -> str:
    """SDK keys are high-entropy random strings, so a fast hash is sufficient."""
    return hashlib.sha256(key.encode()).hexdigest()
