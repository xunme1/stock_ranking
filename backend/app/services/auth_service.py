from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.core.config import AUTH_PASSWORD, AUTH_SESSION_HOURS, AUTH_SESSION_SECRET


SESSION_COOKIE_NAME = "stock_ranking_session"


def is_auth_enabled() -> bool:
    values = (AUTH_PASSWORD, AUTH_SESSION_SECRET)
    if any(values) and not all(values):
        raise RuntimeError(
            "Login settings are incomplete. Set STOCK_RANKING_PASSWORD and "
            "STOCK_RANKING_SESSION_SECRET together."
        )
    if AUTH_SESSION_HOURS < 1:
        raise RuntimeError("STOCK_RANKING_SESSION_HOURS must be at least 1")
    if AUTH_SESSION_SECRET and len(AUTH_SESSION_SECRET) < 32:
        raise RuntimeError("STOCK_RANKING_SESSION_SECRET must contain at least 32 characters")
    return all(values)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_session() -> str:
    now = int(time.time())
    payload = json.dumps(
        {"sub": "viewer", "iat": now, "exp": now + AUTH_SESSION_HOURS * 3600},
        separators=(",", ":"),
    ).encode("utf-8")
    payload_part = _encode(payload)
    signature = hmac.new(AUTH_SESSION_SECRET.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_part}.{_encode(signature)}"


def validate_session(token: str | None) -> bool:
    if not token or not is_auth_enabled():
        return False
    try:
        payload_part, signature_part = token.split(".", 1)
        expected = hmac.new(
            AUTH_SESSION_SECRET.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _decode(signature_part)):
            return False
        payload = json.loads(_decode(payload_part))
        return payload.get("sub") == "viewer" and int(payload.get("exp", 0)) >= int(time.time())
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def valid_password(password: str) -> bool:
    return is_auth_enabled() and hmac.compare_digest(password, AUTH_PASSWORD)
