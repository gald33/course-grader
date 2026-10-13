"""Signed login cookie for students: `<student_id>.<expiry>.<hmac>`."""

from __future__ import annotations

import hashlib
import hmac
import time

from app.core.config import get_settings

COOKIE_NAME = "cg_student"
MAX_AGE_SECONDS = 60 * 60 * 24 * 30


def _key() -> bytes:
    settings = get_settings()
    if settings.session_secret:
        return settings.session_secret.encode()
    if settings.supabase_secret_key:
        return hmac.new(settings.supabase_secret_key.strip().encode(), b"cg-student-session", hashlib.sha256).digest()
    raise RuntimeError("Set SESSION_SECRET or SUPABASE_SECRET_KEY to enable student logins")


def _sign(payload: str) -> str:
    return hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()


def issue(student_id: int, now: float | None = None) -> str:
    now = time.time() if now is None else now
    payload = f"{student_id}.{int(now + MAX_AGE_SECONDS)}"
    return f"{payload}.{_sign(payload)}"


def verify(value: str | None, now: float | None = None) -> int | None:
    """The student id in a valid, unexpired cookie, else None."""
    if not value or value.count(".") != 2:
        return None
    student_id, expires, signature = value.split(".")
    if not hmac.compare_digest(signature, _sign(f"{student_id}.{expires}")):
        return None
    now = time.time() if now is None else now
    if not student_id.isdigit() or not expires.isdigit() or int(expires) < now:
        return None
    return int(student_id)
