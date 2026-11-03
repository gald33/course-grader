"""Seed a freshly migrated database for the frontend browser tests (frontend/e2e).

Builds one course through the real API: four students in two teams (one of
them a test student), the default peer-review schedule, and student review
links. Then installs the guided lesson fixture into that course, loads FAKE
answer keys for it through the instructor upload (the real keys are private
and never in this repository: see fake_keys) and publishes it, imports the
42052 course plan (13 draft lessons, FAKE keys too, nothing published), adds
a few more students who each walk through the lesson in one browser
test (so no test sees another's progress), and signs every lesson student in:
the manifest carries a valid cg_student cookie value for each (signed with
SESSION_SECRET, which the backend under test must share).

Writes the ids, review tokens and cookies as JSON so the browser tests know
which pages to open and as whom.

    DATABASE_URL=sqlite:////tmp/e2e.sqlite3 alembic upgrade head
    SESSION_SECRET=... DATABASE_URL=sqlite:////tmp/e2e.sqlite3 python scripts/seed_e2e.py /tmp/e2e-seed.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.lessons import load_fixture, load_plan  # noqa: E402
from app.main import app  # noqa: E402
from app.models.entities import (  # noqa: E402
    Assignment,
    Assignment,
    CriterionResult,
    Enrollment,
    RubricDimensionScore,
    Student,
    Submission,
    SubmissionMember,
)
from app.services import student_session  # noqa: E402
from app.services.scoring import COMPONENT_DIMENSIONS  # noqa: E402

COURSE = {"code": "E2E101", "name": "Smoke Test Course", "year": 2026, "semester": "A"}
STUDENTS = [
    # (national id, name, team, is_test)
    ("900000001", "Dana Smoke", "Alpha", False),
    ("900000002", "Eli Smoke", "Alpha", False),
    ("900000003", "Noa Smoke", "Beta", False),
    ("900000004", "Test Student", "Beta", True),
]
# The guided lesson the tests walk through. Its course code is 42052, so it
# is installed here with an explicit course-mismatch override.
LESSON_FIXTURE = "lesson-2"
# One student per lesson test that saves something (no team needed).
LESSON_STUDENTS = [
    # (role, national id, name)
    ("trees", "900000011", "Lior Lesson"),
    ("experiments", "900000012", "Maya Lesson"),
    ("navigation", "900000013", "Omer Lesson"),
    ("insights", "900000014", "Tal Lesson"),
    ("resilience", "900000015", "Yael Lesson"),
    ("access", "900000016", "Rina Lesson"),
]
# Assignment pages, in a course of their own so its released grade stays off
# the main course's pages: an HW1 the student has not submitted, and an HW2
# they have, scored on the fixed rubric and released.
ASSIGNMENT_COURSE = {"code": "E2E103", "name": "Assignment Test Course", "year": 2026, "semester": "A"}
ASSIGNMENT_STUDENT = ("900000021", "Gil Assign")
ASSIGNMENT_FEEDBACK = "עבודה יפה, כדאי להרחיב את ההשוואה בין המודלים."
# ...and a project scored on a custom rubric (#26), released: one criterion
# the LLM scored, one the instructor overrode.
ASSIGNMENT_PROJECT = "פרויקט גמר"
ASSIGNMENT_CRITERIA = [
    {"name": "שאלת המחקר", "description": "שאלה ברורה שאפשר לענות עליה מהנתונים", "max_points": 20},
    {"name": "בחירת המודל הסופי", "description": "לפחות שלושה מודלים על אותו מדד", "max_points": 30},
]
ASSIGNMENT_RATIONALE = "[cell 2] השאלה מנוסחת היטב"
# Custom rubrics are seeded in a second course (see seed()).
RUBRIC_COURSE = {"code": "E2E102", "name": "Rubric Test Course", "year": 2026, "semester": "A"}
RUBRIC_SCORED = {"name": "השוואת מודלים", "description": "Three or more models, compared on one metric", "max_points": 20}
RUBRIC_UNSCORED = {"name": "Plots", "description": "Results plotted and explained", "max_points": 10}


# The plan imported into the course (its code differs, so with an override).
PLAN = "42052"


def fake_keys(fixture_key: str) -> dict:
    """FAKE answer keys for a fixture, by a fixed rule the browser tests know:
    the LAST option is "correct", the first is wrong, and every text says
    FAKE. They have nothing to do with the real keys."""
    content = load_fixture(fixture_key)
    keys = {}
    for qkey, q in content["questions"].items():
        if q["type"] == "single_choice":
            ids = [o["id"] for o in q["options"]]
            keys[qkey] = {
                "answer": {
                    "correct": [ids[-1]],
                    "feedback": {i: f"FAKE משוב לאפשרות {i}" for i in ids},
                    "misconceptions": {i: f"fake-{i}" for i in ids[:-1]},
                    "explanation": f"FAKE הסבר לשאלה {qkey}",
                }
            }
        else:
            keys[qkey] = {"answer": {"sample_reasoning": ["FAKE נימוק לדוגמה"], "rubric": ["FAKE קריטריון"]}}
    return {content["slug"]: keys}


def _ok(res, status: int = 200):
    if res.status_code != status:
        raise SystemExit(f"{res.request.method} {res.request.url} -> {res.status_code}: {res.text}")
    return res.json()


def seed() -> dict:
    settings = get_settings()
    settings.instructor_token = None  # seed as the instructor, whatever the environment says
    if not settings.session_secret:
        raise SystemExit("seed_e2e needs SESSION_SECRET (the backend under test signs student cookies with it)")
    with TestClient(app) as c:
        if _ok(c.get("/api/courses")):
            raise SystemExit("seed_e2e expects an empty database")
        course_id = _ok(c.post("/api/courses", json=COURSE))["id"]

        ids: dict[str, int] = {}
        with SessionLocal() as db:
            for national_id, name, _team, is_test in STUDENTS:
                s = Student(national_id=national_id, name=name)
                db.add(s)
                db.flush()
                db.add(Enrollment(course_id=course_id, student_id=s.id, is_test=is_test))
                ids[name] = s.id
            for _role, national_id, name in LESSON_STUDENTS:
                s = Student(national_id=national_id, name=name)
                db.add(s)
                db.flush()
                db.add(Enrollment(course_id=course_id, student_id=s.id, is_test=False))
                ids[name] = s.id
            db.commit()

        base = f"/api/courses/{course_id}/peer"
        teams = {
            team: _ok(c.post(f"{base}/teams", json={"name": f"Team {team}", "project_title": f"Project {team}"}))["id"]
            for team in sorted({t for *_, t, _ in STUDENTS})
        }
        for _nid, name, team, _ in STUDENTS:
            _ok(c.put(f"{base}/students/{ids[name]}/team", json={"team_id": teams[team]}))
        _ok(c.post(f"{base}/setup"))
        _ok(c.post(f"{base}/links/generate"))
        tokens = {row["student_id"]: row["token"] for row in _ok(c.get(f"{base}/links"))}

        # The lesson, the way an instructor does it: install the fixture as a
        # draft (validated, asset files and hashes included), then publish it.
        lessons = f"/api/courses/{course_id}/lessons"
        lesson = _ok(c.post(f"{lessons}/install", json={"fixture_key": LESSON_FIXTURE, "allow_course_mismatch": True}))
        draft = lesson["draft_version"]
        _ok(c.post(f"/api/courses/{course_id}/answer-keys", json={"lessons": fake_keys(LESSON_FIXTURE)}))
        lesson = _ok(c.post(f"{lessons}/{lesson['id']}/publish", json={"version_id": draft["id"]}))

        # The whole-course plan: 13 draft lessons, with FAKE keys so the
        # preview can check answers. Nothing of it is published.
        plan = _ok(c.post(f"/api/courses/{course_id}/plan/import", json={"plan_code": PLAN, "allow_course_mismatch": True}))
        plan_keys: dict = {}
        for session in load_plan(PLAN)["sessions"]:
            for key in [session["fixture_key"], *session.get("enrichment_fixture_keys", [])]:
                plan_keys.update(fake_keys(key))
        _ok(c.post(f"/api/courses/{course_id}/answer-keys", json={"lessons": plan_keys}))
        plan_lessons = {s["lesson_slug"]: s["lesson"]["id"] for s in plan["sessions"]}
        plan_lessons.update({l["slug"]: l["id"] for s in plan["sessions"] for l in s.get("enrichment_lessons", [])})
        assignment_course_id = _ok(c.post("/api/courses", json=ASSIGNMENT_COURSE))["id"]
        with SessionLocal() as db:
            s = Student(national_id=ASSIGNMENT_STUDENT[0], name=ASSIGNMENT_STUDENT[1])
            db.add(s)
            db.flush()
            db.add(Enrollment(course_id=assignment_course_id, student_id=s.id, is_test=False))
            hw1 = Assignment(course_id=assignment_course_id, workcode=1, name="תרגיל 1: היכרות", assignment_type="HW1")
            hw2 = Assignment(course_id=assignment_course_id, workcode=2, name="תרגיל 2: מודלים", assignment_type="HW2")
            a_project = Assignment(course_id=assignment_course_id, workcode=3, name=ASSIGNMENT_PROJECT, assignment_type="PROJECT")
            db.add_all([hw1, hw2, a_project])
            db.flush()
            sub = Submission(
                course_id=assignment_course_id,
                assignment_id=hw2.id,
                group_identifier=ASSIGNMENT_STUDENT[0],
                feedback_student=ASSIGNMENT_FEEDBACK,
            )
            db.add(sub)
            db.flush()
            db.add(SubmissionMember(submission_id=sub.id, student_id=s.id))
            for d in COMPONENT_DIMENSIONS["hw2_code"]:
                db.add(RubricDimensionScore(submission_id=sub.id, component="hw2_code", dimension_key=d.key, raw_score=4, adjusted_score=4))
            db.commit()
            project_sub = Submission(course_id=assignment_course_id, assignment_id=a_project.id, group_identifier=ASSIGNMENT_STUDENT[0])
            db.add(project_sub)
            db.flush()
            db.add(SubmissionMember(submission_id=project_sub.id, student_id=s.id))
            db.commit()
            assignment_student_id, a_hw1_id, a_hw2_id = s.id, hw1.id, hw2.id
            a_project_id, a_project_sub_id = a_project.id, project_sub.id
        a_rubric = _ok(
            c.put(
                f"/api/courses/{assignment_course_id}/assignments/{a_project_id}/rubric",
                json={"criteria": ASSIGNMENT_CRITERIA},
            )
        )["rubric"]
        question, models = (crit["id"] for crit in a_rubric["criteria"])
        with SessionLocal() as db:
            db.add(
                CriterionResult(
                    submission_id=a_project_sub_id, criterion_id=question, status="scored", score=16, rationale=ASSIGNMENT_RATIONALE, model="seed"
                )
            )
            db.commit()
        _ok(c.put(f"/api/submissions/{a_project_sub_id}/custom-rubric/{models}/override", json={"score": 24, "note": "seed"}))
        apeer = f"/api/courses/{assignment_course_id}/peer"
        _ok(c.post(f"{apeer}/links/generate"))
        assignment_token = next(r["token"] for r in _ok(c.get(f"{apeer}/links")) if r["student_id"] == assignment_student_id)
        for component in ("hw2", "project"):
            _ok(c.put(f"/api/courses/{assignment_course_id}/grade-releases/{component}", json={"released": True}))

        # Custom rubrics, in a course of their own so its submission stays off
        # the main course's pages: an HW2 with none (the tests author one), and
        # a project whose rubric has one criterion the LLM scored and one it
        # could not, on one submission.
        rubric_course_id = _ok(c.post("/api/courses", json=RUBRIC_COURSE))["id"]
        with SessionLocal() as db:
            hw2 = Assignment(course_id=rubric_course_id, workcode=2, name="HW2 smoke", assignment_type="HW2")
            project = Assignment(course_id=rubric_course_id, workcode=3, name="Project smoke", assignment_type="PROJECT")
            db.add_all([hw2, project])
            db.flush()
            submission = Submission(course_id=rubric_course_id, assignment_id=project.id, group_identifier="Alpha")
            db.add(submission)
            db.commit()
            hw2_id, project_id, submission_id = hw2.id, project.id, submission.id
        rubric = _ok(
            c.put(
                f"/api/courses/{rubric_course_id}/assignments/{project_id}/rubric",
                json={"criteria": [RUBRIC_SCORED, RUBRIC_UNSCORED]},
            )
        )["rubric"]
        scored, unscored = (crit["id"] for crit in rubric["criteria"])
        with SessionLocal() as db:
            db.add(
                CriterionResult(
                    submission_id=submission_id,
                    criterion_id=scored,
                    status="scored",
                    score=14,
                    rationale="[cell 3] שלושה מודלים הושוו",
                    model="seed",
                )
            )
            db.add(
                CriterionResult(
                    submission_id=submission_id,
                    criterion_id=unscored,
                    status="not_scored",
                    rationale="",
                    model="seed",
                    error="ANTHROPIC_API_KEY is not set",
                )
            )
            db.commit()

    def signed_in(name: str) -> dict:
        student_id = ids[name]
        return {"id": student_id, "name": name, "token": tokens[student_id], "cookie": student_session.issue(student_id)}

    student = STUDENTS[0]
    return {
        "course": {"id": course_id, **COURSE},
        "student": {**signed_in(student[1]), "team": f"Team {student[2]}"},
        "lesson": {
            "id": lesson["id"],
            "slug": lesson["slug"],
            "title": lesson["title"],
            "version_id": lesson["active_version"]["id"],
            "version_number": lesson["active_version"]["number"],
        },
        "lesson_students": {role: signed_in(name) for role, _nid, name in LESSON_STUDENTS},
        "plan_lessons": plan_lessons,
        "test_student": {"id": ids[STUDENTS[3][1]], "name": STUDENTS[3][1]},
        "assignments": {
            "course_id": assignment_course_id,
            "student": {"id": assignment_student_id, "name": ASSIGNMENT_STUDENT[1], "token": assignment_token},
            "hw1": {"id": a_hw1_id, "name": "תרגיל 1: היכרות"},
            "hw2": {"id": a_hw2_id, "name": "תרגיל 2: מודלים", "score": 80, "feedback": ASSIGNMENT_FEEDBACK},
            "project": {
                "id": a_project_id,
                "name": ASSIGNMENT_PROJECT,
                "criteria": ASSIGNMENT_CRITERIA,
                "scores": [16, 24],
                "rationale": ASSIGNMENT_RATIONALE,
            },
        },
        "rubrics": {
            "course_id": rubric_course_id,
            "hw2_id": hw2_id,
            "project_id": project_id,
            "project_submission_id": submission_id,
            "criteria": [{"id": scored, **RUBRIC_SCORED}, {"id": unscored, **RUBRIC_UNSCORED}],
        },
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/seed_e2e.py OUTPUT.json")
    Path(sys.argv[1]).write_text(json.dumps(seed(), indent=2))
