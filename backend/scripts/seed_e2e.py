"""Seed a freshly migrated database for the frontend browser tests (frontend/e2e).

Builds one course through the real API: four students in two teams (one of
them a test student), the default peer-review schedule, and student review
links. Then installs the guided lesson fixture into that course and publishes
it, adds a few more students who each walk through the lesson in one browser
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
from app.main import app  # noqa: E402
from app.models.entities import Enrollment, Student  # noqa: E402
from app.services import student_session  # noqa: E402

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
        lesson = _ok(c.post(f"{lessons}/{lesson['id']}/publish", json={"version_id": draft["id"]}))

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
        "test_student": {"id": ids[STUDENTS[3][1]], "name": STUDENTS[3][1]},
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/seed_e2e.py OUTPUT.json")
    Path(sys.argv[1]).write_text(json.dumps(seed(), indent=2))
