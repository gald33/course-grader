"""The project bonus lives only in `bonus` component overrides."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_db
from app.core.config import get_settings

from app.main import app
from app.models.entities import Course, Enrollment, Student, StudentComponentOverride
from app.services.scoring import compute_gradebook_rows


def _course_with_student(db: Session) -> tuple[int, int]:
    course = Course(code="AI101", name="Applied AI", year=2026, semester="A", attendance_threshold=80)
    student = Student(national_id="111111111", name="Test Student")
    db.add_all([course, student])
    db.commit()
    db.add(Enrollment(course_id=course.id, student_id=student.id, attendance_percent=100.0))
    db.commit()
    return course.id, student.id


def test_bonus_overrides_sum_into_gradebook_bonus(db_engine):
    with Session(db_engine) as db:
        course_id, student_id = _course_with_student(db)
        db.add_all(
            [
                StudentComponentOverride(course_id=course_id, student_id=student_id, component="bonus", delta=3.0, reason="studio help"),
                StudentComponentOverride(course_id=course_id, student_id=student_id, component="bonus", delta=1.5, reason="presentation"),
            ]
        )
        db.commit()
        row = compute_gradebook_rows(db, course_id)[0]

    assert row["bonus_points"] == 4.5
    assert row["project_with_bonus"] == row["project_base"] + 4.5


def test_enrollment_bonus_endpoint_is_gone():
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/courses/{course_id}/enrollments/{enrollment_id}/bonus" not in paths
    assert not hasattr(Enrollment, "bonus_points")


def test_presentation_import_bonus_becomes_override(db_engine, tmp_path, monkeypatch):
    """A non-zero bonus cell in the presentations xlsx adds a `bonus` override
    instead of touching the enrollment; a zero cell adds nothing."""
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "instructor_token", None)
    SessionLocal = sessionmaker(bind=db_engine)
    with SessionLocal() as db:
        course = Course(code="AI101", name="Applied AI", year=2026, semester="A", attendance_threshold=80)
        db.add(course)
        db.add_all([Student(national_id="123456789", name="Bonus"), Student(national_id="987654321", name="Zero")])
        db.commit()
        course_id = course.id

    def _db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    try:
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "sample_presentations.xlsx"
        with TestClient(app) as client, fixture.open("rb") as fh:
            res = client.post(f"/api/courses/{course_id}/imports/presentations", files={"file": ("p.xlsx", fh)})
        assert res.status_code == 200, res.text
        assert res.json()["bonus_updates"] == 1
    finally:
        app.dependency_overrides.clear()

    with SessionLocal() as db:
        overrides = db.scalars(select(StudentComponentOverride).where(StudentComponentOverride.course_id == course_id)).all()
        assert [(o.component, o.delta, o.reason) for o in overrides] == [("bonus", 1.0, "Presentation import (presentation)")]
        row = next(r for r in compute_gradebook_rows(db, course_id) if r["national_id"] == "123456789")
        assert row["bonus_points"] == 1.0


def _alembic(db_url: str, *args: str) -> None:
    backend = Path(__file__).resolve().parents[2]
    env = {**os.environ, "DATABASE_URL": db_url}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=backend, env=env, check=True, capture_output=True)


def _retire_migration() -> tuple[str, str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend = Path(__file__).resolve().parents[2]
    script = ScriptDirectory.from_config(Config(str(backend / "alembic.ini")))
    rev = next(r for r in script.walk_revisions() if r.revision.endswith("_retire_bonus_points"))
    return rev.revision, rev.down_revision


def test_retire_migration_preserves_totals_for_old_and_new_code(tmp_path):
    """Phase 1 moves bonus_points into tagged `bonus` overrides and zeroes the
    column, so the old formula (column + overrides) and the new one (overrides
    only) give the same total; the downgrade moves them back."""
    revision, down_revision = _retire_migration()
    url = f"sqlite:///{tmp_path / 'm.sqlite3'}"
    _alembic(url, "upgrade", down_revision)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO courses (id, code, name, year, semester, attendance_threshold) VALUES (1, 'A', 'A', 2026, 'A', 80)"))
        for sid, bonus in ((1, 4.5), (2, 0.0), (3, -1.0)):
            conn.execute(text("INSERT INTO students (id, national_id, name) VALUES (:i, :n, 'x')"), {"i": sid, "n": str(sid)})
            conn.execute(
                text("INSERT INTO enrollments (course_id, student_id, attendance_exempt, bonus_points, is_test) VALUES (1, :s, 0, :b, 0)"),
                {"s": sid, "b": bonus},
            )
        conn.execute(
            text("INSERT INTO student_component_overrides (course_id, student_id, component, delta, reason, created_at) "
                 "VALUES (1, 1, 'bonus', 2, 'manual', '2026-01-01')")
        )

    def old_totals() -> dict[int, float]:
        with engine.connect() as conn:
            return dict(conn.execute(text(
                "SELECT e.student_id, e.bonus_points + COALESCE((SELECT SUM(o.delta) FROM student_component_overrides o "
                "WHERE o.course_id = e.course_id AND o.student_id = e.student_id AND o.component = 'bonus'), 0) "
                "FROM enrollments e"
            )).all())

    expected = {1: 6.5, 2: 0.0, 3: -1.0}
    assert old_totals() == expected

    _alembic(url, "upgrade", revision)
    assert old_totals() == expected
    with engine.begin() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM enrollments WHERE bonus_points <> 0")).scalar() == 0
        # New code doesn't map the column; the server default fills it.
        conn.execute(text("INSERT INTO students (id, national_id, name) VALUES (4, '4', 'y')"))
        conn.execute(text("INSERT INTO enrollments (course_id, student_id, attendance_exempt, is_test) VALUES (1, 4, 0, 0)"))
    _alembic(url, "upgrade", "head")  # the current code needs every later migration too
    with Session(engine) as db:
        new_totals = {r["national_id"]: r["bonus_points"] for r in compute_gradebook_rows(db, 1)}
    assert new_totals == {"1": 6.5, "2": 0.0, "3": -1.0, "4": 0.0}

    _alembic(url, "downgrade", down_revision)
    assert old_totals() == {**expected, 4: 0.0}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT bonus_points FROM enrollments WHERE student_id = 1")).scalar() == 4.5
        assert conn.execute(text("SELECT reason FROM student_component_overrides")).scalars().all() == ["manual"]
    engine.dispose()
