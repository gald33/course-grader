"""Student login with email + password (Supabase Auth). After signing in,
students land on their per-course review page (/r/<token>)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import Course, Enrollment, Student
from app.services import student_session, supabase_auth
from app.services.peer_review import new_review_token, utcnow

router = APIRouter(prefix="/api/student-auth", tags=["student-auth"])

MIN_PASSWORD_LENGTH = 8


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class SetPasswordIn(BaseModel):
    access_token: str = Field(max_length=4096)
    password: str = Field(max_length=200)


class ForgotIn(BaseModel):
    email: str = Field(max_length=320)


class ChangePasswordIn(BaseModel):
    email: str = Field(max_length=320)
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


def _fail(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _student_by_email(db: Session, email: str) -> Student | None:
    return db.scalar(select(Student).where(Student.email == email.strip().lower()))


def _destinations(db: Session, student: Student) -> dict:
    rows = db.execute(
        select(Enrollment, Course).join(Course).where(Enrollment.student_id == student.id).order_by(Course.year.desc())
    ).all()
    courses = []
    for enrollment, course in rows:
        if not enrollment.review_token:
            enrollment.review_token = new_review_token()
        courses.append({"course_id": course.id, "name": course.name, "url": f"/r/{enrollment.review_token}"})
    db.commit()
    return {"name": student.name, "courses": courses, "redirect": courses[0]["url"] if len(courses) == 1 else None}


def _start_session(response: Response, request: Request, student: Student) -> None:
    response.set_cookie(
        student_session.COOKIE_NAME,
        student_session.issue(student.id),
        max_age=student_session.MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )


def _require_configured() -> None:
    if not supabase_auth.configured():
        raise _fail(503, "not_configured", "Student accounts are not configured on this server")


@router.post("/login")
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    _require_configured()
    student = _student_by_email(db, payload.email)
    try:
        user = supabase_auth.sign_in(payload.email.strip().lower(), payload.password)
    except supabase_auth.AuthError:
        raise _fail(401, "invalid_credentials", "Wrong email or password")
    student = student or _student_by_email(db, user.email)
    if student is None:
        raise _fail(403, "not_enrolled", "This account is not on any course roster")
    if student.account_activated_at is None:
        # First login with the initial password (the national ID): no session
        # until the student picks their own password.
        return {"must_change_password": True}
    _start_session(response, request, student)
    return _destinations(db, student)


@router.post("/change-password")
def change_password(
    payload: ChangePasswordIn, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict:
    """Replace the current password (required at first login)."""
    _require_configured()
    student = _student_by_email(db, payload.email)
    if len(payload.new_password) < MIN_PASSWORD_LENGTH:
        raise _fail(422, "weak_password", f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if payload.new_password == payload.current_password or (
        student is not None and payload.new_password == student.national_id
    ):
        raise _fail(422, "same_password", "Choose a password different from your ID number")
    try:
        user = supabase_auth.sign_in(payload.email.strip().lower(), payload.current_password)
    except supabase_auth.AuthError:
        raise _fail(401, "invalid_credentials", "Wrong email or password")
    student = student or _student_by_email(db, user.email)
    if student is None:
        raise _fail(403, "not_enrolled", "This account is not on any course roster")
    try:
        supabase_auth.admin_set_password(user.id, payload.new_password)
    except supabase_auth.AuthError as exc:
        raise _fail(422, "weak_password", exc.message)
    student.auth_user_id = student.auth_user_id or user.id
    student.account_activated_at = utcnow()
    _start_session(response, request, student)
    return _destinations(db, student)


@router.post("/set-password")
def set_password(payload: SetPasswordIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    """Finish an invite or a password reset (token from the email link)."""
    _require_configured()
    if len(payload.password) < MIN_PASSWORD_LENGTH:
        raise _fail(422, "weak_password", f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    try:
        user = supabase_auth.set_password(payload.access_token, payload.password)
    except supabase_auth.AuthError as exc:
        if "password" in exc.code:
            raise _fail(422, "weak_password", exc.message)
        raise _fail(401, "link_expired", "This link has expired or was already used")
    student = _student_by_email(db, user.email)
    if student is None:
        raise _fail(403, "not_enrolled", "This account is not on any course roster")
    student.account_activated_at = student.account_activated_at or utcnow()
    _start_session(response, request, student)
    return _destinations(db, student)


@router.post("/forgot")
def forgot_password(payload: ForgotIn, db: Session = Depends(get_db)) -> dict:
    """Always answers the same way, so it can't be used to probe the roster."""
    _require_configured()
    student = _student_by_email(db, payload.email)
    if student is not None and student.invited_at is not None:
        try:
            supabase_auth.send_password_reset(student.email)
        except supabase_auth.AuthError:
            pass
    return {"status": "ok"}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)) -> dict:
    student_id = student_session.verify(request.cookies.get(student_session.COOKIE_NAME))
    student = db.get(Student, student_id) if student_id else None
    if student is None:
        raise _fail(401, "not_signed_in", "Not signed in")
    return _destinations(db, student)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(student_session.COOKIE_NAME)
    return {"status": "ok"}
