"""Instructor view of student accounts: emails, account status, creating
accounts (initial password = national ID, changed at first login), password
resets, and email invites (when Supabase has an SMTP server)."""

from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import Course, Enrollment, Student
from app.services import supabase_auth
from app.services.peer_review import utcnow

router = APIRouter(prefix="/api/courses/{course_id}/accounts", tags=["accounts"])


class InviteIn(BaseModel):
    # None = everyone with an email who hasn't activated yet.
    student_ids: list[int] | None = None


def _iso(dt) -> str | None:
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if dt else None


def _students(db: Session, course_id: int) -> list[Student]:
    if not db.get(Course, course_id):
        raise HTTPException(status_code=404, detail="Course not found")
    return list(
        db.scalars(select(Student).join(Enrollment).where(Enrollment.course_id == course_id).order_by(Student.name))
    )


@router.get("")
def list_accounts(course_id: int, db: Session = Depends(get_db)) -> dict:
    return {
        "configured": supabase_auth.configured(),
        "login_url": supabase_auth.callback_url().rsplit("/auth/callback", 1)[0] + "/login",
        "students": [
            {
                "student_id": s.id,
                "name": s.name,
                "national_id": s.national_id,
                "email": s.email,
                "has_account": bool(s.auth_user_id),
                "invited_at": _iso(s.invited_at),
                "activated_at": _iso(s.account_activated_at),
            }
            for s in _students(db, course_id)
        ],
    }


@router.post("/invite")
def send_invites(course_id: int, payload: InviteIn, db: Session = Depends(get_db)) -> dict:
    """Email each selected student a link to choose their password. Students
    who already activated are skipped (they can use "forgot password")."""
    if not supabase_auth.configured():
        raise HTTPException(status_code=503, detail="Student accounts need SUPABASE_PROJECT_URL and SUPABASE_SECRET_KEY")
    wanted = set(payload.student_ids) if payload.student_ids is not None else None
    results = []
    for student in _students(db, course_id):
        if wanted is not None and student.id not in wanted:
            continue
        if not student.email:
            results.append({"student_id": student.id, "status": "no_email"})
            continue
        if student.account_activated_at is not None:
            results.append({"student_id": student.id, "status": "already_active"})
            continue
        try:
            supabase_auth.invite(student.email, student.name)
        except supabase_auth.AuthError as exc:
            if exc.code == "email_exists":
                # Accepted outside this app (e.g. via the dashboard).
                student.account_activated_at = student.account_activated_at or utcnow()
                results.append({"student_id": student.id, "status": "already_active"})
            else:
                results.append({"student_id": student.id, "status": "error", "error": exc.message})
            continue
        student.invited_at = utcnow()
        results.append({"student_id": student.id, "status": "invited"})
        db.commit()
    db.commit()
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"counts": counts, "results": results}


def _require_accounts() -> None:
    if not supabase_auth.configured():
        raise HTTPException(status_code=503, detail="Student accounts need SUPABASE_PROJECT_URL and SUPABASE_SECRET_KEY")


@router.post("/create")
def create_accounts(course_id: int, payload: InviteIn, db: Session = Depends(get_db)) -> dict:
    """Create accounts with the national ID as the initial password (no email
    is sent). Students must pick their own password at first login."""
    _require_accounts()
    wanted = set(payload.student_ids) if payload.student_ids is not None else None
    results = []
    for student in _students(db, course_id):
        if wanted is not None and student.id not in wanted:
            continue
        if not student.email:
            results.append({"student_id": student.id, "status": "no_email"})
            continue
        if student.auth_user_id:
            results.append({"student_id": student.id, "status": "exists"})
            continue
        try:
            user = supabase_auth.create_user(student.email, student.national_id, student.name)
            student.auth_user_id = user.id
            student.invited_at = utcnow()
            student.account_activated_at = None
            results.append({"student_id": student.id, "status": "created"})
        except supabase_auth.AuthError as exc:
            if exc.code == "email_exists":
                # Already has an account (e.g. from an earlier invite): link it, keep its password.
                student.auth_user_id = supabase_auth.find_user_id(student.email)
                results.append({"student_id": student.id, "status": "exists"})
            else:
                results.append({"student_id": student.id, "status": "error", "error": exc.message})
        db.commit()
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"counts": counts, "results": results}


@router.post("/{student_id}/reset-password")
def reset_password(course_id: int, student_id: int, db: Session = Depends(get_db)) -> dict:
    """Set the password back to the national ID; the student must change it
    again at next login."""
    _require_accounts()
    student = next((s for s in _students(db, course_id) if s.id == student_id), None)
    if student is None or not student.email:
        raise HTTPException(status_code=404, detail="Student not found or has no email")
    user_id = student.auth_user_id or supabase_auth.find_user_id(student.email)
    if user_id is None:
        raise HTTPException(status_code=409, detail="This student has no account yet")
    try:
        supabase_auth.admin_set_password(user_id, student.national_id)
    except supabase_auth.AuthError as exc:
        raise HTTPException(status_code=502, detail=exc.message)
    student.auth_user_id = user_id
    student.account_activated_at = None
    db.commit()
    return {"status": "ok"}
