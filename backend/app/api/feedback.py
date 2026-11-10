"""The Feedback button's endpoints, and the ticket API org-core's roles read.

- POST /api/r/<token>/feedback — a student, from any of their pages. The link
  token names the enrollment (as on the rest of the portal); a signed-in
  cg_student cookie must name the same student, and the X-CG-Student header is
  required (a custom header forces a CORS preflight, so another site can't post
  as the student). A withdrawn student can still send feedback.
- POST /api/feedback — the instructor, from any instructor page (the instructor
  middleware guards it like every other instructor route).
- /api/admin/feedback — tickets-core's read and write API (SPEC §17: `read: api`,
  `write: api`): the list `org tickets --source api` pages to exhaustion, one
  ticket, its notes, a new note, and a status or kinds change. It answers the
  ORG_TICKETS_TOKEN service token as a Bearer credential, or the instructor.
"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import auth
from app.api.deps import get_db
from app.core.config import get_settings
from app.models.entities import Enrollment
from app.services import feedback as svc
from app.services import student_session

WRITE_HEADER = "x-cg-student"

student_router = APIRouter(prefix="/api/r/{token}/feedback", tags=["feedback"])
router = APIRouter(prefix="/api/feedback", tags=["feedback"])
admin_router = APIRouter(prefix="/api/admin/feedback", tags=["feedback-admin"])


class FeedbackIn(BaseModel):
    category: str
    text: str
    context: dict[str, Any] = Field(default_factory=dict)


class StudentFeedbackIn(FeedbackIn):
    anonymous: bool = False


class InstructorFeedbackIn(FeedbackIn):
    course_id: int | None = None


class NoteIn(BaseModel):
    author: str
    note: str
    meta: dict[str, Any] = Field(default_factory=dict)


class TicketPatch(BaseModel):
    status: str | None = None
    kinds: list[str] | None = None


def _fail(exc: svc.FeedbackError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


def _student_enrollment(token: str, request: Request, db: Session) -> Enrollment:
    enrollment = db.scalar(select(Enrollment).where(Enrollment.review_token == token)) if len(token) >= 16 else None
    if enrollment is None:
        raise HTTPException(status_code=404, detail={"code": "invalid_link", "message": "Unknown review link"})
    if request.headers.get(WRITE_HEADER) != "1":
        raise HTTPException(status_code=403, detail={"code": "bad_request_origin", "message": "Missing X-CG-Student header"})
    cookie = request.cookies.get(student_session.COOKIE_NAME)
    if cookie:
        try:
            student_id = student_session.verify(cookie)
        except RuntimeError:  # no signing key configured: the cookie can't be checked, so it says nothing
            student_id = None
        if student_id is not None and student_id != enrollment.student_id:
            raise HTTPException(
                status_code=403,
                detail={"code": "wrong_account", "message": "Signed in as a different student than this link belongs to"},
            )
    return enrollment


@student_router.post("")
def student_feedback(token: str, payload: StudentFeedbackIn, request: Request, db: Session = Depends(get_db)) -> dict:
    enrollment = _student_enrollment(token, request, db)
    try:
        ticket = svc.file_ticket(
            db,
            source="student",
            category=payload.category,
            text=payload.text,
            context=payload.context,
            course_id=enrollment.course_id,
            enrollment=enrollment,
            anonymous=payload.anonymous,
        )
    except svc.FeedbackError as exc:
        raise _fail(exc) from None
    return {"id": ticket.id, "status": ticket.status, "anonymous": payload.anonymous}


@router.post("")
def instructor_feedback(payload: InstructorFeedbackIn, db: Session = Depends(get_db)) -> dict:
    try:
        ticket = svc.file_ticket(
            db,
            source="instructor",
            category=payload.category,
            text=payload.text,
            context=payload.context,
            course_id=payload.course_id,
        )
    except svc.FeedbackError as exc:
        raise _fail(exc) from None
    return {"id": ticket.id, "status": ticket.status}


def require_ticket_reader(request: Request) -> None:
    """The service token as `Authorization: Bearer …`, or the instructor."""
    expected = get_settings().org_tickets_token
    supplied = request.headers.get("authorization", "")
    if expected and supplied.startswith("Bearer ") and hmac.compare_digest(supplied[7:].strip(), expected):
        return
    if auth.is_instructor_request(request):
        return
    raise HTTPException(status_code=401, detail="Ticket service token or instructor authentication required")


@admin_router.get("", dependencies=[Depends(require_ticket_reader)])
def admin_list(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[dict]:
    if status is not None and status not in svc.STATUSES:
        raise HTTPException(status_code=422, detail={"code": "invalid_status", "message": "Unknown status"})
    return svc.list_tickets(db, limit=limit, offset=offset, status=status)


@admin_router.get("/{ticket_id}", dependencies=[Depends(require_ticket_reader)])
def admin_get(ticket_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        return svc.get_ticket(db, ticket_id)
    except svc.FeedbackError as exc:
        raise _fail(exc) from None


@admin_router.patch("/{ticket_id}", dependencies=[Depends(require_ticket_reader)])
def admin_update(ticket_id: str, payload: TicketPatch, db: Session = Depends(get_db)) -> dict:
    try:
        return svc.update_ticket(db, ticket_id, status=payload.status, kinds=payload.kinds)
    except svc.FeedbackError as exc:
        raise _fail(exc) from None


@admin_router.get("/{ticket_id}/notes", dependencies=[Depends(require_ticket_reader)])
def admin_notes(ticket_id: str, db: Session = Depends(get_db)) -> list[dict]:
    try:
        return svc.list_notes(db, ticket_id)
    except svc.FeedbackError as exc:
        raise _fail(exc) from None


@admin_router.post("/{ticket_id}/notes", dependencies=[Depends(require_ticket_reader)])
def admin_add_note(ticket_id: str, payload: NoteIn, db: Session = Depends(get_db)) -> dict:
    try:
        return svc.add_note(db, ticket_id, author=payload.author, note=payload.note, meta=payload.meta)
    except svc.FeedbackError as exc:
        raise _fail(exc) from None
