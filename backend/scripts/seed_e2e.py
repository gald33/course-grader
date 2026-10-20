"""Seed a freshly migrated database for the frontend smoke test (frontend/e2e).

Builds one course through the real API: four students in two teams (one of
them a test student), the default peer-review schedule, and student review
links. Writes the ids and one student's review token as JSON so the browser
test knows which pages to open.

    DATABASE_URL=sqlite:////tmp/e2e.sqlite3 alembic upgrade head
    DATABASE_URL=sqlite:////tmp/e2e.sqlite3 python scripts/seed_e2e.py /tmp/e2e-seed.json
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

COURSE = {"code": "E2E101", "name": "Smoke Test Course", "year": 2026, "semester": "A"}
STUDENTS = [
    # (national id, name, team, is_test)
    ("900000001", "Dana Smoke", "Alpha", False),
    ("900000002", "Eli Smoke", "Alpha", False),
    ("900000003", "Noa Smoke", "Beta", False),
    ("900000004", "Test Student", "Beta", True),
]


def _ok(res, status: int = 200):
    if res.status_code != status:
        raise SystemExit(f"{res.request.method} {res.request.url} -> {res.status_code}: {res.text}")
    return res.json()


def seed() -> dict:
    get_settings().instructor_token = None  # seed as the instructor, whatever the environment says
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

    student = STUDENTS[0]
    return {
        "course": {"id": course_id, **COURSE},
        "student": {"name": student[1], "team": f"Team {student[2]}", "token": tokens[ids[student[1]]]},
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/seed_e2e.py OUTPUT.json")
    Path(sys.argv[1]).write_text(json.dumps(seed(), indent=2))
