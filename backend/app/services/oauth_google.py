from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.core.config import get_settings

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

settings = get_settings()


def _client_secret_path() -> Path:
    return Path(settings.google_client_secret_path)


def _token_path() -> Path:
    return Path(settings.google_token_path)


def has_client_secret() -> bool:
    return _client_secret_path().exists()


def load_credentials() -> Credentials | None:
    token_path = _token_path()
    if not token_path.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds if creds and creds.valid else None


def get_authorization_url(state: str = "course-grader") -> str:
    if not has_client_secret():
        raise FileNotFoundError(f"Google client secret file not found at {settings.google_client_secret_path}")
    flow = Flow.from_client_secrets_file(str(_client_secret_path()), scopes=SCOPES)
    flow.redirect_uri = settings.oauth_redirect_uri
    auth_url, _ = flow.authorization_url(access_type="offline", include_granted_scopes="true", state=state, prompt="consent")
    return auth_url


def exchange_code_for_token(code: str) -> dict[str, Any]:
    if not has_client_secret():
        raise FileNotFoundError(f"Google client secret file not found at {settings.google_client_secret_path}")
    flow = Flow.from_client_secrets_file(str(_client_secret_path()), scopes=SCOPES)
    flow.redirect_uri = settings.oauth_redirect_uri
    flow.fetch_token(code=code)
    creds = flow.credentials
    token_path = _token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return json.loads(creds.to_json())
