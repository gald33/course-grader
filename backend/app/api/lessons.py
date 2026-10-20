"""Instructor API for guided lessons: install a lesson fixture as a draft,
preview it, publish versions, and see where students' understanding breaks
down. Answer keys and every student's activity appear only here.

Protected like every other instructor route (see INSTRUCTOR_TOKEN in
app/main.py); student routes live in app/api/student_lessons.py.
"""

from __future__ import annotations

from typing import Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.lessons.schema import Answer
from app.models.entities import Course, Lesson
from app.services import lessons as svc

router = APIRouter(prefix="/api/courses/{course_id}/lessons", tags=["lessons"])


class InstallIn(BaseModel):
    fixture_key: str = Field(max_length=64)
    allow_course_mismatch: bool = False


class LessonUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    # "" clears it; otherwise an https:// Colab or Drive link.
    colab_url: str | None = Field(default=None, max_length=1000)
    # "draft" unpublishes (hidden from students, progress kept); publish via /publish.
    status: Literal["draft", "archived"] | None = None
    position: int | None = Field(default=None, ge=0, le=10000)


class PublishIn(BaseModel):
    version_id: int


class EvaluateIn(BaseModel):
    version_id: int | None = None  # default: the latest version
    question_key: str = Field(max_length=64)
    answer: Answer | None = None
    reveal: bool = False
    prior_answers: int = Field(default=0, ge=0)


class FlagIn(BaseModel):
    flagged: bool


def raise_lesson(exc: svc.LessonError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message, **exc.extra})


def _course(db: Session, course_id: int) -> Course:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


def _lesson(db: Session, course_id: int, lesson_id: int) -> Lesson:
    lesson = db.get(Lesson, lesson_id)
    if not lesson or lesson.course_id != course_id:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return lesson


@router.get("")
def list_lessons(course_id: int, db: Session = Depends(get_db)) -> list[dict]:
    _course(db, course_id)
    return svc.course_lessons(db, course_id)


@router.get("/fixtures")
def list_fixtures(course_id: int, db: Session = Depends(get_db)) -> list[dict]:
    return svc.fixtures_overview(db, _course(db, course_id))


@router.post("/install")
def install(course_id: int, payload: InstallIn, db: Session = Depends(get_db)) -> dict:
    course = _course(db, course_id)
    try:
        lesson, _plan = svc.install_fixture(db, course, payload.fixture_key, payload.allow_course_mismatch)
    except svc.LessonError as exc:
        raise_lesson(exc)
    return svc.lesson_summary(db, lesson)


@router.patch("/{lesson_id}")
def update_lesson(course_id: int, lesson_id: int, payload: LessonUpdateIn, db: Session = Depends(get_db)) -> dict:
    lesson = _lesson(db, course_id, lesson_id)
    try:
        svc.update_lesson(db, lesson, payload.title, payload.colab_url, payload.status, payload.position)
    except svc.LessonError as exc:
        raise_lesson(exc)
    return svc.lesson_summary(db, lesson)


@router.post("/{lesson_id}/publish")
def publish(course_id: int, lesson_id: int, payload: PublishIn, db: Session = Depends(get_db)) -> dict:
    lesson = _lesson(db, course_id, lesson_id)
    try:
        svc.publish_version(db, lesson, payload.version_id)
    except svc.LessonError as exc:
        raise_lesson(exc)
    return svc.lesson_summary(db, lesson)


@router.get("/{lesson_id}/preview")
def preview(course_id: int, lesson_id: int, version_id: int | None = None, db: Session = Depends(get_db)) -> dict:
    lesson = _lesson(db, course_id, lesson_id)
    try:
        return svc.preview_payload(db, lesson, version_id)
    except svc.LessonError as exc:
        raise_lesson(exc)


@router.post("/{lesson_id}/preview/evaluate")
def preview_evaluate(course_id: int, lesson_id: int, payload: EvaluateIn, db: Session = Depends(get_db)) -> dict:
    lesson = _lesson(db, course_id, lesson_id)
    try:
        return svc.preview_evaluate(
            db, lesson, payload.version_id, payload.question_key, payload.answer, payload.reveal, payload.prior_answers
        )
    except svc.LessonError as exc:
        raise_lesson(exc)


@router.get("/{lesson_id}/insights")
def insights(course_id: int, lesson_id: int, include_test: bool = False, db: Session = Depends(get_db)) -> dict:
    return svc.insights(db, _lesson(db, course_id, lesson_id), include_test)


@router.get("/{lesson_id}/students/{student_id}")
def student_detail(course_id: int, lesson_id: int, student_id: int, db: Session = Depends(get_db)) -> dict:
    lesson = _lesson(db, course_id, lesson_id)
    try:
        return svc.student_detail(db, lesson, student_id)
    except svc.LessonError as exc:
        raise_lesson(exc)


@router.post("/{lesson_id}/attempts/{attempt_id}/flag")
def flag_attempt(
    course_id: int, lesson_id: int, attempt_id: int, payload: FlagIn, db: Session = Depends(get_db)
) -> dict:
    lesson = _lesson(db, course_id, lesson_id)
    try:
        return svc.flag_attempt(db, lesson, attempt_id, payload.flagged)
    except svc.LessonError as exc:
        raise_lesson(exc)


@router.get("/{lesson_id}/export.csv")
def export_csv(course_id: int, lesson_id: int, db: Session = Depends(get_db)) -> Response:
    lesson = _lesson(db, course_id, lesson_id)
    return Response(
        content=svc.export_csv(db, lesson).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="lesson-{lesson.slug}-progress.csv"'},
    )
