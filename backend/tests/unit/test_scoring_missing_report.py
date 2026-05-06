from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.entities import (
    Artifact,
    Assignment,
    Course,
    Enrollment,
    RubricDimensionScore,
    Student,
    Submission,
    SubmissionMember,
)
from app.services.scoring import REPORT_DIMENSIONS, compute_gradebook_rows


def _build_course_with_project_submission(
    db: Session,
    *,
    add_pdf_artifact: bool,
    missing_report_flag: bool,
) -> int:
    course = Course(
        code="AI101",
        name="Applied AI",
        year=2026,
        semester="A",
        attendance_threshold=80,
    )
    db.add(course)
    db.commit()
    db.refresh(course)

    student = Student(national_id="111111111", name="Test Student")
    db.add(student)
    db.commit()
    db.refresh(student)

    db.add(Enrollment(course_id=course.id, student_id=student.id, attendance_percent=100.0))

    assignment = Assignment(
        course_id=course.id,
        workcode=1,
        name="Final Project",
        assignment_type="PROJECT",
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    submission = Submission(
        course_id=course.id,
        assignment_id=assignment.id,
        group_identifier=student.national_id,
        missing_report_flag=missing_report_flag,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    db.add(SubmissionMember(submission_id=submission.id, student_id=student.id))

    # Fill all project_report rubric dimensions at the top of the scale so we
    # can prove that the gradebook still zeroes them out when the PDF is missing.
    for dim in REPORT_DIMENSIONS:
        db.add(
            RubricDimensionScore(
                submission_id=submission.id,
                component="project_report",
                dimension_key=dim.key,
                raw_score=5.0,
                adjusted_score=5.0,
            )
        )

    if add_pdf_artifact:
        db.add(
            Artifact(
                submission_id=submission.id,
                kind="project_report_pdf",
                filename="report.pdf",
                path="/tmp/report.pdf",
                mime_type="application/pdf",
            )
        )

    db.commit()
    return course.id


def _setup() -> tuple[Session, int]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine), 0


def test_project_report_zeroed_when_pdf_missing_and_flag_unset():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        course_id = _build_course_with_project_submission(
            db, add_pdf_artifact=False, missing_report_flag=False
        )
        rows = compute_gradebook_rows(db, course_id)

    assert len(rows) == 1
    assert rows[0]["project_report"] == 0.0


def test_project_report_zeroed_when_flag_set_even_with_pdf():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        course_id = _build_course_with_project_submission(
            db, add_pdf_artifact=True, missing_report_flag=True
        )
        rows = compute_gradebook_rows(db, course_id)

    assert len(rows) == 1
    assert rows[0]["project_report"] == 0.0


def test_project_report_scored_normally_with_pdf_and_no_flag():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        course_id = _build_course_with_project_submission(
            db, add_pdf_artifact=True, missing_report_flag=False
        )
        rows = compute_gradebook_rows(db, course_id)

    assert len(rows) == 1
    # All six project_report dims at 5.0, weights sum to 1.0 → 100.0.
    assert rows[0]["project_report"] == 100.0


def test_generic_pdf_submission_file_counts_as_present():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        course_id = _build_course_with_project_submission(
            db, add_pdf_artifact=False, missing_report_flag=False
        )
        # Attach a generic submission_file PDF and confirm it satisfies the
        # has-PDF check (matches the existing has_pdf logic in submissions.py).
        submission = db.query(Submission).first()
        db.add(
            Artifact(
                submission_id=submission.id,
                kind="submission_file",
                filename="ID_111111111_WorkCode_1.pdf",
                path="/tmp/sub.pdf",
                mime_type="application/pdf",
            )
        )
        db.commit()
        rows = compute_gradebook_rows(db, course_id)

    assert rows[0]["project_report"] == 100.0
