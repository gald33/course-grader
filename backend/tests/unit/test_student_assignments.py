"""The assignment pages' data (/api/r/<token> "assignments"): every assignment
with its fixed rubric, and scores only while its grade component is released."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.entities import (
    Assignment,
    Enrollment,
    ReviewRound,
    RubricDimensionScore,
    Student,
    Submission,
    SubmissionMember,
)
from app.services.peer_review import new_review_token
from app.services.scoring import CODE_DIMENSIONS


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


# Every dimension at 4/5, except processing_description, which the grader
# moved from the LLM's 4 to 2 (so its rationale no longer applies).
CHANGED = "processing_description"


@pytest.fixture
def course(env):
    c = env.client
    course_id = _ok(c.post("/api/courses", json={"code": "AI", "name": "AI", "year": 2026, "semester": "A"}))["id"]
    with env.Session() as db:
        hw1 = Assignment(course_id=course_id, workcode=1, name="Intro", assignment_type="HW1")
        hw2_old = Assignment(course_id=course_id, workcode=2, name="Models draft", assignment_type="HW2")
        hw2 = Assignment(course_id=course_id, workcode=3, name="Models", assignment_type="HW2")
        project = Assignment(course_id=course_id, workcode=4, name="Project", assignment_type="PROJECT")
        db.add_all([hw1, hw2_old, hw2, project])
        db.flush()
        ids, tokens, subs = {}, {}, {}
        for key, nid, is_test in (("real", "100000001", False), ("test", "900000001", True)):
            s = Student(national_id=nid, name=key.title())
            db.add(s)
            db.flush()
            db.add(Enrollment(course_id=course_id, student_id=s.id, attendance_percent=90.0, is_test=is_test, review_token=new_review_token()))
            for a in (hw1, hw2_old, hw2):
                sub = Submission(
                    course_id=course_id,
                    assignment_id=a.id,
                    group_identifier=f"{nid}-{a.workcode}",
                    feedback_student=f"{a.name}: well done, {key}",
                    notes_private="private grader note",
                )
                db.add(sub)
                db.flush()
                db.add(SubmissionMember(submission_id=sub.id, student_id=s.id))
                subs[(key, a.assignment_type, a.workcode)] = sub.id
            ids[key] = s.id
        for key in ("real", "test"):
            sub_id = subs[(key, "HW2", 3)]
            for d in CODE_DIMENSIONS:
                raw = 2.0 if d.key == CHANGED else 4.0
                db.add(RubricDimensionScore(submission_id=sub_id, component="hw2_code", dimension_key=d.key, raw_score=raw, adjusted_score=raw))
            db.get(Submission, sub_id).code_review_json = json.dumps(
                {
                    "component": "hw2_code",
                    "dimensions": {
                        "models_quality": {"score": 4, "rationale": "שלושה מודלים הושוו", "source": "claude"},
                        CHANGED: {"score": 4, "rationale": "stale rationale", "source": "claude"},
                    },
                }
            )
        db.commit()
        tokens = {
            key: db.query(Enrollment).filter(Enrollment.student_id == sid).one().review_token for key, sid in ids.items()
        }
        assignment_ids = {"hw1": hw1.id, "hw2_old": hw2_old.id, "hw2": hw2.id, "project": project.id}
    return SimpleNamespace(id=course_id, ids=ids, tokens=tokens, a=assignment_ids)


def _release(env, course, component, released=True):
    _ok(env.client.put(f"/api/courses/{course.id}/grade-releases/{component}", json={"released": released}))


def _assignments(env, course, who="real"):
    return {a["id"]: a for a in _ok(env.client.get(f"/api/r/{course.tokens[who]}"))["assignments"]}


def _has_key(obj, wanted: set[str]) -> bool:
    if isinstance(obj, dict):
        return any(k in wanted for k in obj) or any(_has_key(v, wanted) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_key(v, wanted) for v in obj)
    return False


SCORED_KEYS = {"score", "subtotal", "feedback", "rationale", "peer", "adjustment"}


def test_before_release_rubric_only_no_scores(env, course):
    view = _assignments(env, course)
    assert [view[i]["name"] for i in course.a.values()] == ["Intro", "Models draft", "Models", "Project"]
    hw2 = view[course.a["hw2"]]
    assert hw2["released"] is False and hw2["result"] is None
    assert hw2["submission"]["recorded_at"].endswith("Z")
    assert hw2["counts"] is True and view[course.a["hw2_old"]]["counts"] is False
    # The rubric: every fixed dimension and its points, summing to 100.
    (component,) = hw2["rubric"]
    assert component["key"] == "hw2_code"
    assert [d["key"] for d in component["dimensions"]] == [d.key for d in CODE_DIMENSIONS]
    assert sum(d["max"] for d in component["dimensions"]) == pytest.approx(100)
    assert [c["key"] for c in view[course.a["project"]]["rubric"]] == ["project_code", "project_report"]
    assert view[course.a["hw1"]]["rubric"] == []
    # No submission on the project yet.
    assert view[course.a["project"]]["submission"] is None
    # Nothing scored, and nothing the grader wrote, anywhere before release.
    raw = _ok(env.client.get(f"/api/r/{course.tokens['real']}"))["assignments"]
    assert not _has_key(raw, SCORED_KEYS)
    assert "private grader note" not in json.dumps(raw) and "well done" not in json.dumps(raw)


def test_release_shows_breakdown_and_unrelease_hides_it(env, course):
    _release(env, course, "hw2")
    view = _assignments(env, course)
    hw2 = view[course.a["hw2"]]
    result = hw2["result"]
    assert hw2["released"] is True
    gradebook = {r["student_id"]: r for r in _ok(env.client.get(f"/api/courses/{course.id}/gradebook"))["rows"]}
    grades = _ok(env.client.get(f"/api/r/{course.tokens['real']}"))["grades"]
    # The total is the gradebook's, the same as the Grades tab shows.
    assert result["score"] == gradebook[course.ids["real"]]["hw2"] == grades["hw2"]["score"]
    assert result["feedback"] == "Models: well done, real"
    (component,) = result["components"]
    dims = {d["key"]: d for d in component["dimensions"]}
    assert dims["models_quality"]["score"] == pytest.approx(4 / 5 * dims["models_quality"]["max"])
    assert component["subtotal"] == pytest.approx(result["score"])
    assert sum(d["score"] for d in dims.values()) == pytest.approx(component["subtotal"])
    # A rationale shows only on the score it was written for.
    assert dims["models_quality"]["rationale"] == "שלושה מודלים הושוו"
    assert dims[CHANGED]["rationale"] == ""
    assert dims["order"]["rationale"] == ""
    assert "private grader note" not in json.dumps(hw2)

    # Only HW2 is released: HW1 and the project stay unscored.
    assert view[course.a["hw1"]]["result"] is None and view[course.a["project"]]["result"] is None
    # The older HW2 submission is broken down, but the gradebook doesn't count it.
    old = view[course.a["hw2_old"]]["result"]
    assert old["score"] is None and old["peer"] is None and old["feedback"] == "Models draft: well done, real"

    _release(env, course, "hw2", released=False)
    view = _assignments(env, course)
    assert view[course.a["hw2"]]["result"] is None and view[course.a["hw2"]]["released"] is False
    assert not _has_key(list(view.values()), SCORED_KEYS)


def test_manual_grade_replaces_the_breakdown(env, course):
    with env.Session() as db:
        sub = db.query(Submission).filter(Submission.assignment_id == course.a["hw2"]).first()
        sub.manual_grade = 77.0
        member = db.query(SubmissionMember).filter(SubmissionMember.submission_id == sub.id).one().student_id
        db.commit()
    who = "real" if member == course.ids["real"] else "test"
    _release(env, course, "hw2")
    result = _assignments(env, course, who)[course.a["hw2"]]["result"]
    assert result["manual"] is True and result["components"] == [] and result["score"] == 77.0


def test_applied_peer_round_part(env, course):
    with env.Session() as db:
        db.add(ReviewRound(course_id=course.id, number=1, kind="progress", gradebook_task="hw2", peer_weight=0.3))
        db.commit()
    _ok(env.client.post(f"/api/courses/{course.id}/overrides", json={"student_id": course.ids["real"], "component": "peer_round_1", "delta": 90, "reason": "t"}))
    assert _assignments(env, course)[course.a["hw2"]]["result"] is None
    _release(env, course, "hw2")
    result = _assignments(env, course)[course.a["hw2"]]["result"]
    auto = result["components"][0]["subtotal"]
    assert result["peer"] == {"rounds": [1], "weight": 0.3, "peer": 90.0, "auto": auto}
    assert result["score"] == pytest.approx(0.7 * auto + 0.3 * 90)


def test_test_student_and_preview_see_the_same_view(env, course):
    for released in (False, True):
        for component in ("hw1", "hw2", "project"):
            _release(env, course, component, released)
        for who in ("real", "test"):
            own = _ok(env.client.get(f"/api/r/{course.tokens[who]}"))["assignments"]
            preview = _ok(env.client.get(f"/api/courses/{course.id}/peer/student-view/{course.ids[who]}"))["assignments"]
            assert preview == own
    test_view = _assignments(env, course, "test")[course.a["hw2"]]["result"]
    assert test_view["score"] is not None and test_view["feedback"] == "Models: well done, test"
