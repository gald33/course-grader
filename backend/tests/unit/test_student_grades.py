from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.entities import Assignment, Enrollment, Student, Submission, SubmissionMember
from app.services.peer_review import new_review_token


@pytest.fixture
def env(tmp_path, monkeypatch, db_engine):
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)

    def _db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "instructor_token", None)
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, Session=SessionLocal)
    app.dependency_overrides.clear()


def _ok(res, status=200):
    assert res.status_code == status, res.text
    return res.json()


@pytest.fixture
def course(env):
    c = env.client
    course_id = _ok(c.post("/api/courses", json={"code": "AI", "name": "AI", "year": 2026, "semester": "A"}))["id"]
    with env.Session() as db:
        hw1 = Assignment(course_id=course_id, workcode=1, name="HW1", assignment_type="HW1")
        db.add(hw1)
        db.flush()
        ids, tokens = {}, {}
        for key, nid, is_test in (("real", "100000001", False), ("test", "900000001", True)):
            s = Student(national_id=nid, name=key.title())
            db.add(s)
            db.flush()
            e = Enrollment(
                course_id=course_id, student_id=s.id, attendance_percent=90.0, is_test=is_test, review_token=new_review_token()
            )
            db.add(e)
            sub = Submission(course_id=course_id, assignment_id=hw1.id, group_identifier=nid, feedback_student=f"Nice work, {key}")
            db.add(sub)
            db.flush()
            db.add(SubmissionMember(submission_id=sub.id, student_id=s.id))
            ids[key], tokens[key] = s.id, e.review_token
        db.commit()
    return SimpleNamespace(id=course_id, ids=ids, tokens=tokens)


def _release(env, course, component, released=True):
    return _ok(env.client.put(f"/api/courses/{course.id}/grade-releases/{component}", json={"released": released}))


def test_nothing_shows_until_released(env, course):
    assert _ok(env.client.get(f"/api/r/{course.tokens['real']}"))["grades"] == {}
    state = _ok(env.client.get(f"/api/courses/{course.id}/grade-releases"))
    assert [c["key"] for c in state["components"]] == ["hw1", "hw2", "project", "talks", "attendance", "final"]
    assert not any(c["released"] for c in state["components"])


def test_released_components_and_feedback(env, course):
    _release(env, course, "hw1")
    grades = _ok(env.client.get(f"/api/r/{course.tokens['real']}"))["grades"]
    assert grades == {"hw1": {"score": 100.0, "feedback": "Nice work, real"}}

    _release(env, course, "attendance")
    _release(env, course, "final")
    grades = _ok(env.client.get(f"/api/r/{course.tokens['real']}"))["grades"]
    assert set(grades) == {"hw1", "attendance", "final"}
    assert grades["attendance"] == {"percent": 90.0, "threshold": 80.0, "exempt": False, "score": 100.0}
    gradebook = {r["student_id"]: r for r in _ok(env.client.get(f"/api/courses/{course.id}/gradebook"))["rows"]}
    assert grades["final"]["score"] == gradebook[course.ids["real"]]["final"]

    state = _release(env, course, "hw1", released=False)
    assert not next(c for c in state["components"] if c["key"] == "hw1")["released"]
    assert "hw1" not in _ok(env.client.get(f"/api/r/{course.tokens['real']}"))["grades"]


def test_test_student_and_preview_see_the_same_view(env, course):
    for component in ("hw1", "hw2", "project", "talks", "attendance", "final"):
        _release(env, course, component)
    own = _ok(env.client.get(f"/api/r/{course.tokens['test']}"))["grades"]
    assert own["hw1"] == {"score": 100.0, "feedback": "Nice work, test"}
    assert set(own) == {"hw1", "hw2", "project", "talks", "attendance", "final"}
    preview = _ok(env.client.get(f"/api/courses/{course.id}/peer/student-view/{course.ids['test']}"))["grades"]
    assert preview == own
    real = _ok(env.client.get(f"/api/r/{course.tokens['real']}"))["grades"]
    assert real == _ok(env.client.get(f"/api/courses/{course.id}/peer/student-view/{course.ids['real']}"))["grades"]


def test_unknown_component_rejected(env, course):
    res = env.client.put(f"/api/courses/{course.id}/grade-releases/bogus", json={"released": True})
    assert res.status_code == 404
    res = env.client.put("/api/courses/9999/grade-releases/hw1", json={"released": True})
    assert res.status_code == 404
