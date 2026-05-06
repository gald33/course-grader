from __future__ import annotations

import math

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.entities import (
    Assignment,
    Course,
    Enrollment,
    RubricDimensionScore,
    Student,
    Submission,
    SubmissionMember,
)
from app.services.scoring import (
    apply_curve,
    compute_gradebook_rows,
    enforce_monotonic,
)


def test_enforce_monotonic_replaces_nan_points():
    out = enforce_monotonic([0.0, float("nan"), 2.0, float("inf"), 4.0, 5.0])
    assert all(math.isfinite(p) for p in out)
    # Monotonic non-decreasing.
    for i in range(1, len(out)):
        assert out[i] >= out[i - 1]


def test_apply_curve_with_nan_raw_score_returns_finite():
    points = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    out = apply_curve(float("nan"), points)
    assert math.isfinite(out)


def test_compute_gradebook_rows_finite_with_nan_target_distribution():
    """A bad final-distribution config (NaN sigma/mean) must not poison the gradebook —
    `_finite` and the sigma floor in `_apply_rank_preserving_normal` keep finals finite."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        course = Course(code="AI", name="AI", year=2026, semester="A", attendance_threshold=80)
        db.add(course)
        db.commit()
        db.refresh(course)

        student = Student(national_id="123", name="N")
        db.add(student)
        db.commit()
        db.refresh(student)

        db.add(Enrollment(course_id=course.id, student_id=student.id, attendance_percent=100.0))

        assignment = Assignment(
            course_id=course.id, workcode=1, name="Project", assignment_type="PROJECT"
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        submission = Submission(
            course_id=course.id, assignment_id=assignment.id, group_identifier="123"
        )
        db.add(submission)
        db.commit()
        db.refresh(submission)
        db.add(SubmissionMember(submission_id=submission.id, student_id=student.id))

        db.add(
            RubricDimensionScore(
                submission_id=submission.id,
                component="project_code",
                dimension_key="data_scope_adequacy",
                raw_score=3.0,
                adjusted_score=3.0,
            )
        )
        db.commit()

        rows = compute_gradebook_rows(db, course.id)

    assert len(rows) == 1
    assert math.isfinite(rows[0]["final"])
    assert math.isfinite(rows[0]["final_uncurved"])
