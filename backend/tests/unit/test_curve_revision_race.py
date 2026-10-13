from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.entities import Course, CurveRevision, Student
from app.services import scoring


@pytest.fixture
def session_factory(tmp_path):
    # File-backed so each session gets its own connection, like two requests.
    engine = create_engine(f"sqlite:///{tmp_path / 'curves.sqlite3'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


def _create_course(session_factory) -> int:
    with session_factory() as db:
        course = Course(code="AI101", name="Applied AI", year=2026, semester="A")
        db.add(course)
        db.commit()
        return course.id


def _revision_count(session_factory, course_id: int) -> int:
    with session_factory() as db:
        return db.scalar(
            select(func.count()).select_from(CurveRevision).where(CurveRevision.course_id == course_id)
        )


def _lose_first_lookup_race(monkeypatch, session_factory) -> None:
    """The caller's first lookup finds no curve, and before it inserts one a
    parallel request commits revision 1 — the course page firing
    /curves/active and /gradebook at once on a new course."""
    real_lookup = scoring._active_curve
    raced = False

    def lookup(db, course_id):
        nonlocal raced
        if raced:
            return real_lookup(db, course_id)
        raced = True
        with session_factory() as other:
            other.add(
                CurveRevision(
                    course_id=course_id,
                    revision_number=1,
                    mapping_json="{}",
                    note="created by the other request",
                    is_active=True,
                )
            )
            other.commit()
        return None

    monkeypatch.setattr(scoring, "_active_curve", lookup)


def test_first_call_creates_the_default_revision_once(session_factory):
    course_id = _create_course(session_factory)
    with session_factory() as db:
        first = scoring.get_active_curve(db, course_id)
        second = scoring.get_active_curve(db, course_id)
        assert first.id == second.id
        assert first.revision_number == 1
        assert first.note == "Default identity curves"
    assert _revision_count(session_factory, course_id) == 1


def test_losing_the_first_revision_race_returns_the_winners_revision(session_factory, monkeypatch):
    course_id = _create_course(session_factory)
    _lose_first_lookup_race(monkeypatch, session_factory)
    with session_factory() as db:
        curve = scoring.get_active_curve(db, course_id)
        assert curve.note == "created by the other request"
        # The session is still usable after the conflict.
        assert db.scalar(select(func.count()).select_from(Course)) == 1
    assert _revision_count(session_factory, course_id) == 1


def test_losing_the_race_keeps_the_callers_pending_changes(session_factory, monkeypatch):
    # The notebook-run worker calls get_active_curve with the finished run's
    # results still pending in its session; a lost race must not discard them.
    course_id = _create_course(session_factory)
    _lose_first_lookup_race(monkeypatch, session_factory)
    with session_factory() as db:
        db.add(Student(national_id="123456789", name="Pending Student"))
        scoring.get_active_curve(db, course_id)
    with session_factory() as db:
        assert db.scalar(select(Student.name).where(Student.national_id == "123456789")) == "Pending Student"
