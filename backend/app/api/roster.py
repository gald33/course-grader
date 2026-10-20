"""Instructor edits to the roster, one student at a time (no re-import)."""

from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import Course, Enrollment, Student, Team, TeamMembership
from app.services import roster

router = APIRouter(prefix="/api/courses/{course_id}/students", tags=["roster"])


class StudentAddIn(BaseModel):
    national_id: str = Field(max_length=32)
    name: str = Field(max_length=255)
    email: str | None = Field(default=None, max_length=320)


class StudentEditIn(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    # Omit to leave unchanged; null or "" removes it.
    email: str | None = Field(default=None, max_length=320)


def _iso(dt) -> str | None:
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if dt else None


def _fail(exc: roster.RosterError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


def _enrollment(db: Session, course_id: int, student_id: int) -> Enrollment:
    enrollment = db.scalar(
        select(Enrollment).where(Enrollment.course_id == course_id, Enrollment.student_id == student_id)
    )
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Student is not enrolled in this course")
    return enrollment


def _row(enrollment: Enrollment, team_name: str | None) -> dict:
    s = enrollment.student
    return {
        "student_id": s.id,
        "enrollment_id": enrollment.id,
        "national_id": s.national_id,
        "name": s.name,
        "email": s.email,
        "has_account": bool(s.auth_user_id),
        "is_test": enrollment.is_test,
        "withdrawn_at": _iso(enrollment.withdrawn_at),
        "team_name": team_name,
    }


@router.get("")
def list_students(course_id: int, db: Session = Depends(get_db)) -> list[dict]:
    if not db.get(Course, course_id):
        raise HTTPException(status_code=404, detail="Course not found")
    teams = dict(
        db.execute(
            select(TeamMembership.student_id, Team.name)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(TeamMembership.course_id == course_id, TeamMembership.end_at.is_(None))
        ).all()
    )
    enrollments = db.scalars(
        select(Enrollment).join(Student).where(Enrollment.course_id == course_id).order_by(Student.name)
    ).all()
    return [_row(e, teams.get(e.student_id)) for e in enrollments]


@router.post("")
def add_student(course_id: int, payload: StudentAddIn, db: Session = Depends(get_db)) -> dict:
    if not db.get(Course, course_id):
        raise HTTPException(status_code=404, detail="Course not found")
    try:
        enrollment = roster.add_student(db, course_id, payload.national_id, payload.name, payload.email)
    except roster.RosterError as exc:
        db.rollback()
        raise _fail(exc)
    return _row(enrollment, None)


@router.patch("/{student_id}")
def edit_student(course_id: int, student_id: int, payload: StudentEditIn, db: Session = Depends(get_db)) -> dict:
    enrollment = _enrollment(db, course_id, student_id)
    try:
        roster.update_student(
            db,
            enrollment.student,
            name=payload.name,
            email=(payload.email or None) if "email" in payload.model_fields_set else "",
        )
    except roster.RosterError as exc:
        db.rollback()
        raise _fail(exc)
    return {"status": "ok"}


@router.post("/{student_id}/withdraw")
def withdraw_student(course_id: int, student_id: int, db: Session = Depends(get_db)) -> dict:
    roster.withdraw(db, _enrollment(db, course_id, student_id))
    return {"status": "ok"}


@router.post("/{student_id}/reinstate")
def reinstate_student(course_id: int, student_id: int, db: Session = Depends(get_db)) -> dict:
    roster.reinstate(db, _enrollment(db, course_id, student_id))
    return {"status": "ok"}
