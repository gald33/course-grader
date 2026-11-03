"""Instructor API for a course plan (the whole syllabus as draft lessons, the
session schedule and each lesson's readiness) and for the private answer
keys. Protected like every other instructor route (see INSTRUCTOR_TOKEN in
app/main.py).

The answer-key upload takes the instructor's private JSON file as the body
(format: app/services/answer_keys.py). Neither route ever returns a key.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.lessons import raise_lesson
from app.models.entities import Course
from app.services import answer_keys
from app.services import course_plan as svc
from app.services.lessons import LessonError

router = APIRouter(prefix="/api/courses/{course_id}", tags=["course-plan"])


class PlanImportIn(BaseModel):
    plan_code: str = Field(max_length=64)
    allow_course_mismatch: bool = False


class MarksIn(BaseModel):
    reviewed: bool | None = None
    live_verified: bool | None = None


def _course(db: Session, course_id: int) -> Course:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@router.get("/plan")
def get_plan(course_id: int, db: Session = Depends(get_db)) -> dict:
    return svc.plan_view(db, _course(db, course_id))


@router.post("/plan/import")
def import_plan(course_id: int, payload: PlanImportIn, db: Session = Depends(get_db)) -> dict:
    course = _course(db, course_id)
    try:
        return svc.import_plan(db, course, payload.plan_code, payload.allow_course_mismatch)
    except LessonError as exc:
        raise_lesson(exc)


@router.patch("/plan/sessions/{number}")
def set_marks(course_id: int, number: int, payload: MarksIn, db: Session = Depends(get_db)) -> dict:
    course = _course(db, course_id)
    try:
        return svc.set_marks(db, course, number, payload.reviewed, payload.live_verified)
    except LessonError as exc:
        raise_lesson(exc)


@router.get("/answer-keys")
def key_status(course_id: int, db: Session = Depends(get_db)) -> dict:
    return answer_keys.key_status(db, _course(db, course_id))


@router.post("/answer-keys")
def import_keys(
    course_id: int,
    body: Any = Body(...),
    dry_run: bool = False,
    confirm_published_breaks: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    """dry_run validates and reports; confirm_published_breaks stores keys
    that leave a published version unable to check a question (409 without)."""
    course = _course(db, course_id)
    try:
        return answer_keys.import_keys(
            db, course, body, source="upload", dry_run=dry_run, confirm_published_breaks=confirm_published_breaks
        )
    except answer_keys.BreaksPublishedVersion as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "breaks_published_version",
                "message": "These keys don't fit a published version students may be on; nothing was stored. "
                "Confirm to store them anyway.",
                "errors": exc.errors,
                "published_versions_not_fitting": exc.breaks,
            },
        ) from None
    except answer_keys.KeyImportError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_answer_keys", "message": "The answer-key file has errors; nothing was stored", "errors": exc.errors},
        ) from None
