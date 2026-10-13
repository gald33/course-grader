"""Student accounts on Supabase Auth (email = username, invite to set a password).

The backend talks to Supabase Auth with the project secret key; the browser
never needs Supabase keys. Supabase sends the invite and password-reset emails
(through the SMTP server configured in the Supabase dashboard); their links
come back to PUBLIC_APP_URL/auth/callback with an access token in the URL
fragment, which the set-password page hands to `set_password`.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import get_settings

# Tests swap in an httpx.MockTransport.
_transport: httpx.BaseTransport | None = None


class AuthError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class AuthUser:
    id: str
    email: str


def configured() -> bool:
    settings = get_settings()
    return bool(settings.supabase_project_url and settings.supabase_secret_key)


def callback_url() -> str:
    return get_settings().public_app_url.rstrip("/") + "/auth/callback"


def _client(user_token: str | None = None) -> httpx.Client:
    settings = get_settings()
    if not configured():
        raise AuthError("not_configured", "Student accounts need SUPABASE_PROJECT_URL and SUPABASE_SECRET_KEY")
    key = settings.supabase_secret_key.strip()
    return httpx.Client(
        base_url=settings.supabase_project_url.strip().rstrip("/") + "/auth/v1",
        headers={"apikey": key, "Authorization": f"Bearer {user_token or key}"},
        timeout=30,
        transport=_transport,
    )


def _error(response: httpx.Response) -> AuthError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    code = body.get("error_code") or body.get("code") or body.get("error") or f"http_{response.status_code}"
    message = body.get("msg") or body.get("message") or body.get("error_description") or response.text[:200]
    return AuthError(str(code), str(message))


def _user(data: dict) -> AuthUser:
    return AuthUser(id=str(data["id"]), email=str(data.get("email", "")).lower())


def invite(email: str, name: str) -> None:
    """Email an invite link to choose a password. Supabase re-sends to a user
    who was invited but hasn't accepted yet; it refuses (email_exists) once
    the account is active."""
    with _client() as client:
        res = client.post(
            "/invite", params={"redirect_to": callback_url()}, json={"email": email, "data": {"name": name}}
        )
    if res.is_error:
        raise _error(res)


def send_password_reset(email: str) -> None:
    with _client() as client:
        res = client.post("/recover", params={"redirect_to": callback_url()}, json={"email": email})
    if res.is_error:
        raise _error(res)


def sign_in(email: str, password: str) -> AuthUser:
    with _client() as client:
        res = client.post("/token", params={"grant_type": "password"}, json={"email": email, "password": password})
    if res.is_error:
        raise _error(res)
    return _user(res.json()["user"])


def user_for_token(access_token: str) -> AuthUser:
    with _client(access_token) as client:
        res = client.get("/user")
    if res.is_error:
        raise _error(res)
    return _user(res.json())


def set_password(access_token: str, password: str) -> AuthUser:
    """Finish an invite or reset: the access token comes from the email link."""
    with _client(access_token) as client:
        res = client.put("/user", json={"password": password})
    if res.is_error:
        raise _error(res)
    return _user(res.json())
