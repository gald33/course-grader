"""Student-facing guided lessons, under the student's course link
(/api/r/<token>/lessons).

The instructor middleware exempts /api/r/ from the instructor token; that is
not authorization. Every route here resolves the link token AND the signed
cg_student cookie, and they must name the same student. Writes also need the
X-CG-Student header (a custom header forces a CORS preflight, so another site
can't post with the student's cookie). Nothing here takes a student or
enrollment id from the client.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NoReturn, TypeVar

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.lessons.schema import AttemptInput, CommitmentInput, ExperimentInput, FinalInput, ProgressPatch, RevealInput
from app.models.entities import Enrollment, Lesson
from app.services import lessons as svc
from app.services import student_session

router = APIRouter(prefix="/api/r/{token}/lessons", tags=["student-lessons"])

WRITE_HEADER = "x-cg-student"

M = TypeVar("M", bound=BaseModel)


def _fail(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def raise_lesson(exc: svc.LessonError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message, **exc.extra})


def resolve_lesson_enrollment(token: str, request: Request, db: Session = Depends(get_db)) -> Enrollment:
    enrollment = db.scalar(select(Enrollment).where(Enrollment.review_token == token)) if len(token) >= 16 else None
    if enrollment is None:
        raise _fail(404, "invalid_link", "Unknown review link")
    try:
        student_id = student_session.verify(request.cookies.get(student_session.COOKIE_NAME))
    except RuntimeError:  # no signing key configured: nobody can be signed in
        student_id = None
    if student_id is None:
        raise _fail(401, "not_signed_in", "Not signed in")
    if student_id != enrollment.student_id:
        raise _fail(403, "wrong_account", "Signed in as a different student than this link belongs to")
    if request.method not in ("GET", "HEAD"):
        if request.headers.get(WRITE_HEADER) != "1":
            raise _fail(403, "bad_request_origin", "Missing X-CG-Student header")
        # A withdrawn student can still read their lessons, not change anything.
        if enrollment.withdrawn_at is not None:
            raise _fail(409, "withdrawn", "You have withdrawn from this course")
    return enrollment


def _lesson(db: Session, enrollment: Enrollment, slug: str) -> Lesson:
    try:
        return svc.student_lesson(db, enrollment, slug)
    except svc.LessonError as exc:
        raise_lesson(exc)


def _parse(model: type[M], body: Any) -> M:
    """The request body as `model`; type errors come back as the same
    field-level invalid_values the service uses for out-of-range values."""
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        fields: dict[str, str] = {}
        for error in exc.errors():
            number = error["type"] in ("float_type", "int_type", "int_from_float", "finite_number")
            fields.setdefault(".".join(str(p) for p in error["loc"]) or "body", svc.MSG["number" if number else "invalid"])
        raise svc.invalid_values(fields) from None


def _run(fn: Callable[[], dict]) -> dict:
    try:
        return fn()
    except svc.LessonError as exc:
        raise_lesson(exc)


@router.get("")
def list_lessons(
    enrollment: Enrollment = Depends(resolve_lesson_enrollment), db: Session = Depends(get_db)
) -> dict:
    return {"lessons": svc.student_lessons(db, enrollment)}


@router.get("/{slug}")
def get_lesson(
    slug: str, enrollment: Enrollment = Depends(resolve_lesson_enrollment), db: Session = Depends(get_db)
) -> dict:
    return svc.student_payload(db, enrollment, _lesson(db, enrollment, slug))


@router.patch("/{slug}/progress")
def patch_progress(
    slug: str,
    body: dict = Body(...),
    enrollment: Enrollment = Depends(resolve_lesson_enrollment),
    db: Session = Depends(get_db),
) -> dict:
    lesson = _lesson(db, enrollment, slug)
    return _run(lambda: svc.patch_progress(db, enrollment, lesson, _parse(ProgressPatch, body)))


@router.post("/{slug}/attempts")
def submit_attempt(
    slug: str,
    body: dict = Body(...),
    enrollment: Enrollment = Depends(resolve_lesson_enrollment),
    db: Session = Depends(get_db),
) -> dict:
    lesson = _lesson(db, enrollment, slug)
    return _run(lambda: svc.submit_attempt(db, enrollment, lesson, _parse(AttemptInput, body)))


@router.post("/{slug}/questions/{question_key}/reveal")
def reveal(
    slug: str,
    question_key: str,
    body: dict = Body(...),
    enrollment: Enrollment = Depends(resolve_lesson_enrollment),
    db: Session = Depends(get_db),
) -> dict:
    lesson = _lesson(db, enrollment, slug)
    return _run(lambda: svc.reveal(db, enrollment, lesson, question_key, _parse(RevealInput, body).request_id))


@router.put("/{slug}/experiments/{run_uuid}")
def save_experiment(
    slug: str,
    run_uuid: str,
    body: dict = Body(...),
    enrollment: Enrollment = Depends(resolve_lesson_enrollment),
    db: Session = Depends(get_db),
) -> dict:
    lesson = _lesson(db, enrollment, slug)
    return _run(lambda: svc.save_experiment(db, enrollment, lesson, run_uuid, _parse(ExperimentInput, body)))


@router.delete("/{slug}/experiments/{run_uuid}")
def delete_experiment(
    slug: str,
    run_uuid: str,
    expected_revision: int,
    enrollment: Enrollment = Depends(resolve_lesson_enrollment),
    db: Session = Depends(get_db),
) -> dict:
    lesson = _lesson(db, enrollment, slug)
    return _run(lambda: svc.delete_experiment(db, enrollment, lesson, run_uuid, expected_revision))


@router.post("/{slug}/commitments")
def commit(
    slug: str,
    body: dict = Body(...),
    enrollment: Enrollment = Depends(resolve_lesson_enrollment),
    db: Session = Depends(get_db),
) -> dict:
    lesson = _lesson(db, enrollment, slug)
    return _run(lambda: svc.commit(db, enrollment, lesson, _parse(CommitmentInput, body)))


@router.patch("/{slug}/commitments/{commitment_id}/final")
def record_final(
    slug: str,
    commitment_id: int,
    body: dict = Body(...),
    enrollment: Enrollment = Depends(resolve_lesson_enrollment),
    db: Session = Depends(get_db),
) -> dict:
    lesson = _lesson(db, enrollment, slug)
    return _run(lambda: svc.record_final(db, enrollment, lesson, commitment_id, _parse(FinalInput, body)))
