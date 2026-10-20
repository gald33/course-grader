"""The project bonus lives only in `bonus` component overrides."""

from __future__ import annotations

from sqlalchemy.orm import Session

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
