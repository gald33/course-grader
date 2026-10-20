"""Student accounts on Supabase Auth (email = username).

The backend talks to Supabase Auth with the project secret key; the browser
never needs Supabase keys. Two ways to give students access:

- Instructor-created accounts (no email needed): the initial password is the
  student's national ID and must be changed at first login.
- Invites by email (needs an SMTP server configured in Supabase): the link
  comes back to PUBLIC_APP_URL/auth/callback with an access token in the URL
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


# --- Instructor-created accounts (no email needed) --------------------------


def create_user(email: str, password: str, name: str) -> AuthUser:
    """Create a confirmed account with an initial password. Raises AuthError
    with code "email_exists" if the email already has an account."""
    with _client() as client:
        res = client.post(
            "/admin/users",
            json={"email": email, "password": password, "email_confirm": True, "user_metadata": {"name": name}},
        )
    if res.is_error:
        raise _error(res)
    return _user(res.json())


def admin_set_password(user_id: str, password: str) -> None:
    with _client() as client:
        res = client.put(f"/admin/users/{user_id}", json={"password": password})
    if res.is_error:
        raise _error(res)


def find_user_id(email: str) -> str | None:
    """Look up an existing account by email (a course has tens of users)."""
    email = email.lower()
    with _client() as client:
        page = 1
        while True:
            res = client.get("/admin/users", params={"page": page, "per_page": 1000})
            if res.is_error:
                raise _error(res)
            users = res.json().get("users", [])
            for user in users:
                if str(user.get("email", "")).lower() == email:
                    return str(user["id"])
            if len(users) < 1000:
                return None
            page += 1


def admin_set_email(user_id: str, email: str) -> None:
    """Fix a student's sign-in email (confirmed, no email round-trip)."""
    with _client() as client:
        res = client.put(f"/admin/users/{user_id}", json={"email": email, "email_confirm": True})
    if res.is_error:
        raise _error(res)
