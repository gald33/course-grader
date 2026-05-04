from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app.services.oauth_google import exchange_code_for_token, get_authorization_url

router = APIRouter(prefix="/api/oauth/google", tags=["oauth"])


@router.get("/start")
def oauth_start() -> dict:
    try:
        url = get_authorization_url()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"authorization_url": url}


@router.get("/callback")
def oauth_callback(code: str) -> HTMLResponse:
    try:
        exchange_code_for_token(code)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return HTMLResponse("<html><body><h3>Google OAuth completed. You can return to course-grader.</h3></body></html>")
