"""Per-student roster edits: add one student, fix a name or email, withdraw
or reinstate. Withdrawn students stay enrolled (their history is kept) but are
left out of teams, review obligations and the gradebook."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Enrollment, PeerReview, ReviewObligation, ReviewRound, Student
from app.services import supabase_auth
from app.services import peer_review as svc
from app.services.peer_review import utcnow
from app.utils.text import normalize_id

WITHDRAWN_REASON = "Withdrawn from the course"


class RosterError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def withdrawn_ids(db: Session, course_id: int) -> set[int]:
    return set(
        db.scalars(
            select(Enrollment.student_id).where(Enrollment.course_id == course_id, Enrollment.withdrawn_at.is_not(None))
        )
    )


def clean_email(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    if "@" not in text or " " in text:
        raise RosterError("invalid_email", "Enter a valid email address", 422)
    return text


def _clean_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise RosterError("invalid_name", "The student needs a name", 422)
    return name


def update_student(db: Session, student: Student, name: str | None = None, email: str | None = "") -> Student:
    """Fix the name and/or email (email="" leaves it unchanged, None clears it).
    The student record is shared by every course the student is in. If the
    student already has a sign-in account, its email is changed too, so the
    student signs in with the corrected address."""
    if name is not None:
        student.name = _clean_name(name)
    if email != "":
        new_email = clean_email(email)
        if new_email != student.email:
            if new_email and db.scalar(select(Student.id).where(Student.email == new_email, Student.id != student.id)):
                raise RosterError("email_taken", "Another student already has this email")
            if student.email and supabase_auth.configured():
                try:
                    user_id = student.auth_user_id or supabase_auth.find_user_id(student.email)
                    if user_id and new_email is None:
                        raise RosterError("account_needs_email", "This student has an account; its email can be changed but not removed")
                    if user_id:
                        supabase_auth.admin_set_email(user_id, new_email)
                        student.auth_user_id = user_id
                except supabase_auth.AuthError as exc:
                    raise RosterError("auth_error", f"Could not update the sign-in account: {exc.message}", 502)
            student.email = new_email
    db.commit()
    db.refresh(student)
    return student


def add_student(db: Session, course_id: int, national_id: str, name: str, email: str | None) -> Enrollment:
    """Enrol one student. A student already known from another course is
    reused (and their name/email updated to what was entered)."""
    nid = normalize_id(national_id)
    if not nid:
        raise RosterError("invalid_national_id", "Enter the student's ID number", 422)
    name = _clean_name(name)
    student = db.scalar(select(Student).where(Student.national_id == nid))
    if student is None:
        email = clean_email(email)
        if email and db.scalar(select(Student.id).where(Student.email == email)):
            raise RosterError("email_taken", "Another student already has this email")
        student = Student(national_id=nid, name=name, email=email)
        db.add(student)
        db.flush()
    else:
        enrollment = db.scalar(
            select(Enrollment).where(Enrollment.course_id == course_id, Enrollment.student_id == student.id)
        )
        if enrollment is not None:
            if enrollment.withdrawn_at is not None:
                raise RosterError("already_enrolled", "This student is withdrawn from the course; reinstate them instead")
            raise RosterError("already_enrolled", "This student is already in the course")
        update_student(db, student, name=name, email=email if email else "")
    enrollment = Enrollment(course_id=course_id, student_id=student.id)
    db.add(enrollment)
    db.commit()
    svc.refresh_practice_rounds(db, course_id)
    db.refresh(enrollment)
    return enrollment


def withdraw(db: Session, enrollment: Enrollment) -> None:
    """Mark withdrawn, take them off their team, and exempt the reviews they
    still owe in rounds that haven't been released. Reviews they already
    wrote are kept and still count for the teams they reviewed."""
    if enrollment.withdrawn_at is not None:
        return
    enrollment.withdrawn_at = utcnow()
    db.commit()
    svc.remove_student_from_team(db, enrollment.course_id, enrollment.student_id)
    reviewed = select(PeerReview.presentation_id).where(PeerReview.reviewer_student_id == enrollment.student_id)
    for ob in db.scalars(
        select(ReviewObligation)
        .join(ReviewRound, ReviewRound.id == ReviewObligation.round_id)
        .where(
            ReviewRound.course_id == enrollment.course_id,
            ReviewRound.released_at.is_(None),
            ReviewObligation.student_id == enrollment.student_id,
            ReviewObligation.exempt.is_(False),
            ReviewObligation.presentation_id.not_in(reviewed),
        )
    ):
        ob.exempt = True
        ob.exempt_reason = WITHDRAWN_REASON
    db.commit()


def reinstate(db: Session, enrollment: Enrollment) -> None:
    """Undo a withdrawal. The student has no team (the instructor or the
    student picks one) and the exemptions made at withdrawal stay; the
    instructor can lift them per round."""
    if enrollment.withdrawn_at is None:
        return
    enrollment.withdrawn_at = None
    db.commit()
    svc.refresh_practice_rounds(db, enrollment.course_id)
