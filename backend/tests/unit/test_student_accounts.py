from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.entities import Enrollment, Student
from app.services import student_session, supabase_auth

SECRET = "sb_secret_test"


class FakeSupabaseAuth:
    """The slice of the Supabase Auth API used by app.services.supabase_auth."""

    def __init__(self) -> None:
        self.users: dict[str, dict] = {}  # email -> {id, password, confirmed}
        self.tokens: dict[str, str] = {}  # access token -> email
        self.invites: list[tuple[str, str]] = []
        self.resets: list[str] = []

    def token_for(self, email: str) -> str:
        token = f"tok-{email}"
        self.tokens[token] = email
        return token

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["apikey"] == SECRET
        path = request.url.path.removeprefix("/auth/v1")
        body = json.loads(request.content) if request.content else {}
        bearer = request.headers["authorization"].removeprefix("Bearer ")
        if path == "/invite":
            user = self.users.get(body["email"])
            if user and user["confirmed"]:
                return httpx.Response(422, json={"error_code": "email_exists", "msg": "already registered"})
            self.users.setdefault(body["email"], {"id": f"u-{len(self.users)}", "password": None, "confirmed": False})
            self.invites.append((body["email"], request.url.params["redirect_to"]))
            return httpx.Response(200, json={"id": self.users[body["email"]]["id"]})
        if path == "/admin/users" and request.method == "POST":
            if body["email"] in self.users:
                return httpx.Response(422, json={"error_code": "email_exists", "msg": "already registered"})
            self.users[body["email"]] = {"id": f"u-{len(self.users)}", "password": body["password"], "confirmed": True}
            return httpx.Response(200, json={"id": self.users[body["email"]]["id"], "email": body["email"]})
        if path == "/admin/users" and request.method == "GET":
            return httpx.Response(200, json={"users": [{"id": u["id"], "email": e} for e, u in self.users.items()]})
        if path.startswith("/admin/users/") and request.method == "PUT":
            uid = path.rsplit("/", 1)[1]
            email = next(e for e, u in self.users.items() if u["id"] == uid)
            self.users[email]["password"] = body["password"]
            return httpx.Response(200, json={"id": uid, "email": email})
        if path == "/recover":
            self.resets.append(body["email"])
            return httpx.Response(200, json={})
        if path == "/token":
            user = self.users.get(body["email"])
            if not user or user["password"] != body["password"]:
                return httpx.Response(400, json={"error_code": "invalid_credentials", "msg": "Invalid login credentials"})
            return httpx.Response(200, json={"access_token": "x", "user": {"id": user["id"], "email": body["email"]}})
        if path == "/user":
            email = self.tokens.get(bearer)
            if email is None:
                return httpx.Response(401, json={"error_code": "bad_jwt", "msg": "invalid JWT"})
            user = self.users[email]
            if request.method == "PUT":
                if len(body["password"]) < 6:
                    return httpx.Response(422, json={"error_code": "weak_password", "msg": "too short"})
                user["password"], user["confirmed"] = body["password"], True
            return httpx.Response(200, json={"id": user["id"], "email": email})
        return httpx.Response(404, json={"msg": f"unexpected {request.method} {path}"})


@pytest.fixture
def env(db_engine, monkeypatch, tmp_path):
    fake = FakeSupabaseAuth()
    settings = get_settings()
    for name, value in {
        "data_dir": str(tmp_path),
        "instructor_token": None,
        "supabase_project_url": "https://proj.supabase.co",
        "supabase_secret_key": SECRET,
        "public_app_url": "https://grader.example.org",
        "session_secret": None,
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(supabase_auth, "_transport", httpx.MockTransport(fake))
    Session = sessionmaker(bind=db_engine, autoflush=False)

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        course_id = client.post("/api/courses", json={"code": "AI", "name": "AI Products", "year": 2026, "semester": "A"}).json()["id"]
        yield SimpleNamespace(client=client, fake=fake, Session=Session, course_id=course_id, settings=settings)
    app.dependency_overrides.clear()


def _yedion_file(path, rows):
    """Same shape as a Yedion export: a title row, then headers, then data."""
    wb = Workbook()
    ws = wb.active
    ws.append(["רשימת סטודנטים עם סטטיסטיקת שימוש באתר הקורס"])
    ws.append(["תעודת זהות", "שם משפחה", "שם פרטי", "חוג/מסלול", "שנה אקדמית", "שם משפחה לועזי", "שם פרטי לועזי",
               "כתובת הדואר האלקטרוני  חיצוני", "כתובת הדואר האלקטרוני  פנימי", "טלפון סלולרי", "", "כניסות לאתר הקורס"])
    for r in rows:
        ws.append(r)
    wb.save(path)


def _import(env, tmp_path, rows):
    path = tmp_path / "yedion.xlsx"
    _yedion_file(path, rows)
    with open(path, "rb") as fh:
        res = env.client.post(f"/api/courses/{env.course_id}/imports/roster", files={"file": ("y.xlsx", fh)})
    assert res.status_code == 200, res.text
    return res.json()


ROWS = [
    ["111111118", "כהן", "נועה", "x", 0, "Cohen", "Noa", "Noa.Cohen@Gmail.com", "", "050-0000000", "", 3],
    ["222222226", "לוי", "איתי", "x", 0, "Levi", "Itay", "itay@example.com", "", "050-1111111", "", 1],
    ["333333334", "פרץ", "מאיה", "x", 0, "Peretz", "Maya", "", "", "050-2222222", "", 0],
]


def test_yedion_import_keeps_only_id_name_and_email(env, tmp_path):
    result = _import(env, tmp_path, ROWS)
    assert result["imported"] == 3 and result["email_conflicts"] == []
    with env.Session() as db:
        students = {s.national_id: s for s in db.scalars(select(Student))}
    assert students["111111118"].name == "נועה כהן"
    assert students["111111118"].email == "noa.cohen@gmail.com"  # normalised
    assert students["333333334"].email is None
    stored = json.dumps([[s.national_id, s.name, s.email] for s in students.values()], ensure_ascii=False)
    assert "050-" not in stored


def test_invite_set_password_login_and_logout(env, tmp_path):
    _import(env, tmp_path, ROWS)
    c, fake = env.client, env.fake
    res = c.post(f"/api/courses/{env.course_id}/accounts/invite", json={})
    assert res.json()["counts"] == {"invited": 2, "no_email": 1}
    assert {e for e, _ in fake.invites} == {"noa.cohen@gmail.com", "itay@example.com"}
    assert all(redirect == "https://grader.example.org/auth/callback" for _, redirect in fake.invites)

    accounts = {a["email"]: a for a in c.get(f"/api/courses/{env.course_id}/accounts").json()["students"]}
    assert accounts["noa.cohen@gmail.com"]["invited_at"] and not accounts["noa.cohen@gmail.com"]["activated_at"]

    # The invite link's token sets the password and signs the student in.
    token = fake.token_for("noa.cohen@gmail.com")
    assert c.post("/api/student-auth/set-password", json={"access_token": token, "password": "short"}).json()["detail"]["code"] == "weak_password"
    res = c.post("/api/student-auth/set-password", json={"access_token": token, "password": "correct horse"})
    assert res.status_code == 200
    assert res.json()["redirect"].startswith("/r/") and student_session.COOKIE_NAME in res.cookies
    with env.Session() as db:
        enrollment = db.scalar(select(Enrollment).join(Student).where(Student.email == "noa.cohen@gmail.com"))
        assert res.json()["redirect"] == f"/r/{enrollment.review_token}"
    assert c.get("/api/student-auth/me").json()["name"] == "נועה כהן"
    c.post("/api/student-auth/logout")
    c.cookies.clear()
    assert c.get("/api/student-auth/me").status_code == 401

    # Later visits: email + password (email is case-insensitive).
    bad = c.post("/api/student-auth/login", json={"email": "noa.cohen@gmail.com", "password": "nope"})
    assert bad.status_code == 401 and bad.json()["detail"]["code"] == "invalid_credentials"
    good = c.post("/api/student-auth/login", json={"email": "Noa.Cohen@gmail.com ", "password": "correct horse"})
    assert good.status_code == 200 and good.json()["redirect"].startswith("/r/")

    # Already active: re-inviting skips her instead of sending another email.
    sent_before = len(fake.invites)
    res = c.post(f"/api/courses/{env.course_id}/accounts/invite", json={"student_ids": None})
    assert res.json()["counts"]["already_active"] == 1 and len(fake.invites) == sent_before + 1  # only itay again


def test_expired_link_and_accounts_not_on_the_roster(env, tmp_path):
    _import(env, tmp_path, ROWS)
    res = env.client.post("/api/student-auth/set-password", json={"access_token": "garbage", "password": "long enough"})
    assert res.status_code == 401 and res.json()["detail"]["code"] == "link_expired"

    env.fake.users["stranger@example.com"] = {"id": "u-x", "password": "pw123456", "confirmed": True}
    res = env.client.post("/api/student-auth/login", json={"email": "stranger@example.com", "password": "pw123456"})
    assert res.status_code == 403 and res.json()["detail"]["code"] == "not_enrolled"


def test_forgot_password_never_reveals_who_is_enrolled(env, tmp_path):
    _import(env, tmp_path, ROWS)
    env.client.post(f"/api/courses/{env.course_id}/accounts/invite", json={})
    for email in ("unknown@example.com", "itay@example.com"):
        res = env.client.post("/api/student-auth/forgot", json={"email": email})
        assert res.status_code == 200 and res.json() == {"status": "ok"}
    assert env.fake.resets == ["itay@example.com"]


def test_session_cookie_is_tamper_proof(env):
    value = student_session.issue(7)
    assert student_session.verify(value) == 7
    sid, exp, sig = value.split(".")
    assert student_session.verify(f"8.{exp}.{sig}") is None
    assert student_session.verify(student_session.issue(7, now=0)) is None  # expired


def test_student_auth_is_public_but_accounts_need_the_instructor(env, monkeypatch):
    monkeypatch.setattr(env.settings, "instructor_token", "teacher-token")
    assert env.client.get(f"/api/courses/{env.course_id}/accounts").status_code == 401
    assert env.client.post("/api/student-auth/forgot", json={"email": "a@b.c"}).status_code == 200


def _login(env, email, password):
    return env.client.post("/api/student-auth/login", json={"email": email, "password": password})


def test_created_accounts_use_the_id_number_until_changed(env, tmp_path):
    _import(env, tmp_path, ROWS)
    c, fake = env.client, env.fake
    res = c.post(f"/api/courses/{env.course_id}/accounts/create", json={})
    assert res.json()["counts"] == {"created": 2, "no_email": 1}
    assert fake.users["noa.cohen@gmail.com"]["password"] == "111111118"
    assert fake.invites == []  # no email involved
    again = c.post(f"/api/courses/{env.course_id}/accounts/create", json={})
    assert again.json()["counts"] == {"exists": 2, "no_email": 1}

    # First login with the ID number: no session until the password changes.
    first = _login(env, "noa.cohen@gmail.com", "111111118")
    assert first.status_code == 200 and first.json() == {"must_change_password": True}
    assert student_session.COOKIE_NAME not in first.cookies
    assert c.get("/api/student-auth/me").status_code == 401

    change = lambda current, new: c.post(  # noqa: E731
        "/api/student-auth/change-password",
        json={"email": "noa.cohen@gmail.com", "current_password": current, "new_password": new},
    )
    assert change("111111118", "111111118").json()["detail"]["code"] == "same_password"
    assert change("111111118", "short").json()["detail"]["code"] == "weak_password"
    assert change("wrong-current", "a brand new pw").json()["detail"]["code"] == "invalid_credentials"
    done = change("111111118", "a brand new pw")
    assert done.status_code == 200 and done.json()["redirect"].startswith("/r/")
    assert c.get("/api/student-auth/me").json()["name"] == "נועה כהן"

    c.cookies.clear()
    assert _login(env, "noa.cohen@gmail.com", "111111118").status_code == 401  # ID no longer works
    assert _login(env, "noa.cohen@gmail.com", "a brand new pw").json()["redirect"].startswith("/r/")

    # Forgotten password: the instructor resets it to the ID number.
    with env.Session() as db:
        noa = db.scalar(select(Student).where(Student.email == "noa.cohen@gmail.com"))
    assert c.post(f"/api/courses/{env.course_id}/accounts/{noa.id}/reset-password").json() == {"status": "ok"}
    assert _login(env, "noa.cohen@gmail.com", "111111118").json() == {"must_change_password": True}
    accounts = {a["email"]: a for a in c.get(f"/api/courses/{env.course_id}/accounts").json()["students"]}
    assert accounts["noa.cohen@gmail.com"]["has_account"] and accounts["noa.cohen@gmail.com"]["activated_at"] is None


def test_creating_an_account_that_already_exists_links_it(env, tmp_path):
    _import(env, tmp_path, ROWS)
    env.fake.users["itay@example.com"] = {"id": "u-existing", "password": "their own pw", "confirmed": True}
    res = env.client.post(f"/api/courses/{env.course_id}/accounts/create", json={"student_ids": None})
    assert res.json()["counts"] == {"created": 1, "exists": 1, "no_email": 1}
    assert env.fake.users["itay@example.com"]["password"] == "their own pw"  # untouched
    with env.Session() as db:
        itay = db.scalar(select(Student).where(Student.email == "itay@example.com"))
        assert itay.auth_user_id == "u-existing"


def test_test_student_account_for_the_instructor(env, tmp_path):
    _import(env, tmp_path, ROWS)
    c = env.client
    url = f"/api/courses/{env.course_id}/accounts/test-student"
    res = c.post(url, json={"email": " Teacher+Student@Example.com "})
    assert res.status_code == 200, res.text
    made = res.json()
    assert made["email"] == "teacher+student@example.com" and made["initial_password"].startswith("test-")
    assert env.fake.users["teacher+student@example.com"]["password"] == made["initial_password"]
    # Asking again returns the same student; a real student's email is refused.
    assert c.post(url, json={"email": "teacher+student@example.com"}).json()["student_id"] == made["student_id"]
    assert c.post(url, json={"email": "noa.cohen@gmail.com"}).status_code == 409

    accounts = {a["email"]: a for a in c.get(f"/api/courses/{env.course_id}/accounts").json()["students"]}
    assert accounts["teacher+student@example.com"]["is_test"] and not accounts["noa.cohen@gmail.com"]["is_test"]
    # Same first-login rule as everyone: the initial password must be changed.
    first = _login(env, "teacher+student@example.com", made["initial_password"])
    assert first.json() == {"must_change_password": True}
