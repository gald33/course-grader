"""Per-student roster edits: add, fix name/email, withdraw, reinstate."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.entities import Enrollment, ReviewObligation, Student, Team
from app.services import supabase_auth
from test_peer_review_api import GOOD, _base, _ok, _review, _schedule_and_open, course, env  # noqa: F401
from test_student_accounts import SECRET, FakeSupabaseAuth


def _students(env, course_id):
    return {s["student_id"]: s for s in _ok(env.client.get(f"/api/courses/{course_id}/students"))}


def test_add_student_and_fix_name_and_email(env, course):
    c = env.client
    url = f"/api/courses/{course.id}/students"
    row = _ok(c.post(url, json={"national_id": " 400000001 ", "name": "Dana Dor", "email": "Dana@Example.com"}))
    assert (row["national_id"], row["name"], row["email"], row["withdrawn_at"]) == ("400000001", "Dana Dor", "dana@example.com", None)
    sid = row["student_id"]

    res = c.post(url, json={"national_id": "400000001", "name": "Dana Dor"})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "already_enrolled"
    res = c.post(url, json={"national_id": "400000002", "name": "Other", "email": "dana@example.com"})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "email_taken"
    assert c.post(url, json={"national_id": "", "name": "X"}).status_code == 422

    _ok(c.patch(f"{url}/{sid}", json={"name": "Dana Dorot"}))
    assert _students(env, course.id)[sid]["email"] == "dana@example.com"  # untouched
    _ok(c.patch(f"{url}/{sid}", json={"email": "dana.dorot@example.com"}))
    assert _students(env, course.id)[sid]["name"] == "Dana Dorot"
    assert _students(env, course.id)[sid]["email"] == "dana.dorot@example.com"
    res = c.patch(f"{url}/{sid}", json={"email": "not an email"})
    assert res.status_code == 422
    res = c.patch(f"{url}/{course.students['a1']}", json={"email": "dana.dorot@example.com"})
    assert res.json()["detail"]["code"] == "email_taken"

    # A late student owes reviews in an open practice round.
    rnd = _ok(c.post(f"{_base(course)}/rounds/practice", json={"title": "Try it", "open_now": True}))
    late = _ok(c.post(url, json={"national_id": "400000003", "name": "Late Lior"}))["student_id"]
    with env.Session() as db:
        assert db.scalars(
            select(ReviewObligation).where(ReviewObligation.round_id == rnd["round_id"], ReviewObligation.student_id == late)
        ).all()


def test_withdraw_leaves_team_obligations_and_gradebook(env, course):
    c = env.client
    _schedule_and_open(env, course)
    _ok(_review(env, course, "a1", "B"))
    a1 = course.students["a1"]
    # Teams locked by a passed deadline: the instructor can still take a withdrawn student off their team.
    past = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"
    _ok(c.put(f"{_base(course)}/team-settings", json={"teams_deadline": past}))

    _ok(c.post(f"/api/courses/{course.id}/students/{a1}/withdraw"))
    row = _students(env, course.id)[a1]
    assert row["withdrawn_at"] and row["team_name"] is None
    with env.Session() as db:
        obligations = db.scalars(
            select(ReviewObligation).where(ReviewObligation.round_id == course.round_id, ReviewObligation.student_id == a1)
        ).all()
        reviewed = {course.pres["B"]}
        assert obligations and all(o.exempt == (o.presentation_id not in reviewed) for o in obligations)

    teams = _ok(c.get(f"{_base(course)}/teams"))
    assert a1 not in {s["student_id"] for s in teams["students"]}
    assert a1 not in teams["unassigned"]
    assert _ok(c.get(f"{_base(course)}/overview"))["student_count"] == 5
    gradebook = _ok(c.get(f"/api/courses/{course.id}/gradebook"))["rows"]
    assert "100000001" not in {r["national_id"] for r in gradebook} and len(gradebook) == 5
    scores = _ok(c.get(f"{_base(course)}/rounds/{course.round_id}/scores"))
    assert a1 not in {s["student_id"] for s in scores["students"]}
    team_b = next(t for t in scores["teams"] if t["team_name"] == "Team B")
    assert team_b["valid_reviews"] == 1  # the review they wrote still counts

    # Can't be put back on a team while withdrawn; their page is read-only.
    res = c.put(f"{_base(course)}/students/{a1}/team", json={"team_id": course.teams["A"]})
    assert res.status_code == 409
    home = _ok(c.get(f"/api/r/{course.tokens['a1']}"))
    assert home["student"]["withdrawn"] is True and home["team"] is None and home["teams_policy"]["open"] is False
    res = _review(env, course, "a1", "B")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "withdrawn"
    _ok(c.get(f"{_base(course)}/student-view/{a1}"))

    # Reinstating brings them back (no team; the exemptions stay).
    _ok(c.post(f"/api/courses/{course.id}/students/{a1}/reinstate"))
    assert _students(env, course.id)[a1]["withdrawn_at"] is None
    _ok(c.put(f"{_base(course)}/students/{a1}/team", json={"team_id": course.teams["A"]}))
    assert len(_ok(c.get(f"/api/courses/{course.id}/gradebook"))["rows"]) == 6


def test_withdrawing_the_last_member_removes_a_team_without_history(env, course):
    c = env.client
    team = _ok(c.post(f"{_base(course)}/teams", json={"name": "Solo", "project_title": ""}))["id"]
    late = _ok(c.post(f"/api/courses/{course.id}/students", json={"national_id": "500000001", "name": "Solo Sam"}))["student_id"]
    _ok(c.put(f"{_base(course)}/students/{late}/team", json={"team_id": team}))
    _ok(c.post(f"/api/courses/{course.id}/students/{late}/withdraw"))
    with env.Session() as db:
        assert db.get(Team, team) is None
        assert db.scalar(select(Enrollment).where(Enrollment.student_id == late)).withdrawn_at is not None


def test_new_round_skips_withdrawn_students(env, course):
    c = env.client
    c2 = course.students["c2"]
    _ok(c.post(f"/api/courses/{course.id}/students/{c2}/withdraw"))
    _schedule_and_open(env, course)
    with env.Session() as db:
        assert not db.scalars(select(ReviewObligation).where(ReviewObligation.student_id == c2)).all()


@pytest.fixture
def auth_env(db_engine, monkeypatch, tmp_path):
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
        yield SimpleNamespace(client=client, fake=fake, Session=Session, course_id=course_id)
    app.dependency_overrides.clear()


def test_fixing_an_email_moves_the_sign_in_account(auth_env):
    c, fake, cid = auth_env.client, auth_env.fake, auth_env.course_id
    sid = _ok(c.post(f"/api/courses/{cid}/students", json={"national_id": "600000001", "name": "Typo Tal", "email": "tal@exmaple.com"}))["student_id"]
    assert c.post(f"/api/courses/{cid}/accounts/create", json={}).json()["counts"] == {"created": 1}

    _ok(c.patch(f"/api/courses/{cid}/students/{sid}", json={"email": "tal@example.com"}))
    assert "tal@example.com" in fake.users and "tal@exmaple.com" not in fake.users
    res = c.post("/api/student-auth/login", json={"email": "tal@example.com", "password": "600000001"})
    assert res.status_code == 200 and res.json() == {"must_change_password": True}

    res = c.patch(f"/api/courses/{cid}/students/{sid}", json={"email": None})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "account_needs_email"
    with auth_env.Session() as db:
        assert db.get(Student, sid).email == "tal@example.com"


def test_reimport_keeps_a_fixed_email_on_an_account(auth_env, tmp_path):
    from test_student_accounts import _yedion_file

    c, cid = auth_env.client, auth_env.course_id
    row = ["600000002", "טל", "טייפו", "x", 0, "Typo", "Tal", "tal@exmaple.com", "", "", "", 1]
    path = tmp_path / "y.xlsx"
    _yedion_file(path, [row])

    def _import():
        with open(path, "rb") as fh:
            return _ok(c.post(f"/api/courses/{cid}/imports/roster", files={"file": ("y.xlsx", fh)}))

    _import()
    with auth_env.Session() as db:
        sid = db.scalar(select(Student.id).where(Student.national_id == "600000002"))
    assert c.post(f"/api/courses/{cid}/accounts/create", json={}).json()["counts"] == {"created": 1}
    _ok(c.patch(f"/api/courses/{cid}/students/{sid}", json={"email": "tal@example.com"}))

    # The registrar sheet still has the typo: reported, not applied.
    assert _import()["email_conflicts"] == ["600000002"]
    with auth_env.Session() as db:
        assert db.get(Student, sid).email == "tal@example.com"
    res = c.post("/api/student-auth/login", json={"email": "tal@example.com", "password": "600000002"})
    assert res.status_code == 200
