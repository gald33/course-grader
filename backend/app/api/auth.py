"""Optional instructor authentication.

With INSTRUCTOR_TOKEN unset (the default, localhost-only deployment) every
route stays open as before. Once it is set — needed as soon as the app is
reachable by students — instructor routes require the token as the
X-Instructor-Token header or the cg_instructor cookie. The cookie lets
plain links (artifact downloads, exports) work in the browser.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request, Response

from app.core.config import get_settings
from app.schemas.api import InstructorSessionIn

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "cg_instructor"
HEADER_NAME = "x-instructor-token"

# Reachable without the instructor token.
PUBLIC_PATHS = {"/api/health", "/api/oauth/google/callback", "/api/auth/status", "/api/auth/instructor-session"}
STUDENT_PREFIX = "/api/r/"


def token_matches(supplied: str | None) -> bool:
    expected = get_settings().instructor_token
    return bool(expected) and bool(supplied) and hmac.compare_digest(str(supplied), str(expected))


def is_instructor_request(request: Request) -> bool:
    if not get_settings().instructor_token:
        return True
    return token_matches(request.headers.get(HEADER_NAME)) or token_matches(request.cookies.get(COOKIE_NAME))


def requires_instructor(path: str, method: str) -> bool:
    if method == "OPTIONS" or not path.startswith("/api/"):
        return False
    return path not in PUBLIC_PATHS and not path.startswith(STUDENT_PREFIX)


@router.get("/status")
def auth_status(request: Request) -> dict:
    return {
        "required": bool(get_settings().instructor_token),
        "authenticated": is_instructor_request(request),
    }


@router.post("/instructor-session")
def start_session(payload: InstructorSessionIn, request: Request, response: Response) -> dict:
    if not get_settings().instructor_token:
        return {"status": "ok", "required": False}
    if not token_matches(payload.token):
        raise HTTPException(status_code=401, detail="Invalid instructor token")
    response.set_cookie(
        COOKIE_NAME,
        payload.token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=60 * 60 * 24 * 30,
    )
    return {"status": "ok", "required": True}


@router.delete("/instructor-session")
def end_session(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME)
    return {"status": "ok"}
