from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.entities import Course, Submission
from app.services.zip_ingest import ingest_submission_zip


def test_ingest_sample_zip_fixture():
    engine = create_engine('sqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)

    fixture = Path(__file__).resolve().parents[1] / 'fixtures' / 'sample_submissions.zip'

    with Session(engine) as db:
        course = Course(code='AI101', name='Applied AI', year=2026, semester='A', attendance_threshold=80)
        db.add(course)
        db.commit()
        db.refresh(course)

        result = ingest_submission_zip(
            db=db,
            course_id=course.id,
            assignment_type='HW2',
            zip_path=str(fixture),
            fallback_workcode=2,
            assignment_name='HW2'
        )

        submissions = db.scalars(select(Submission)).all()

    assert result.created_submissions == 1
    assert result.stored_artifacts >= 2
    assert len(submissions) == 1
    assert submissions[0].group_identifier == '123456789+987654321'
