"""What a student sees of their own grade: only the gradebook components the
instructor has released, plus the instructor's feedback text on the
submissions those components grade."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Course, Enrollment, GradeRelease
from app.services.peer_review import utcnow
from app.services.scoring import _get_submission_for_student, compute_student_grade_row

# Released one at a time, in this order on the student page.
COMPONENTS = ("hw1", "hw2", "project", "talks", "attendance", "final")


def released_components(db: Session, course_id: int) -> dict[str, GradeRelease]:
    return {r.component: r for r in db.scalars(select(GradeRelease).where(GradeRelease.course_id == course_id))}


def set_released(db: Session, course_id: int, component: str, released: bool) -> None:
    current = released_components(db, course_id).get(component)
    if released and current is None:
        db.add(GradeRelease(course_id=course_id, component=component, released_at=utcnow()))
    elif not released and current is not None:
        db.delete(current)
    db.commit()


def _feedback(db: Session, enrollment: Enrollment, assignment_type: str) -> str:
    submission = _get_submission_for_student(db, enrollment.course_id, enrollment.student_id, assignment_type)
    return (submission.feedback_student or "").strip() if submission else ""


def grades_view(db: Session, enrollment: Enrollment) -> dict:
    """Released components only; an empty dict until the first release, and
    nothing is computed before then."""
    released = released_components(db, enrollment.course_id)
    if not released:
        return {}
    row = compute_student_grade_row(db, enrollment)

    # Marks a part whose score includes applied peer-review rounds.
    def peer(task: str) -> dict:
        return {"peer": True} if task in row["peer"] else {}

    view: dict = {}
    if "hw1" in released:
        view["hw1"] = {"score": row["hw1"], "feedback": _feedback(db, enrollment, "HW1"), **peer("hw1")}
    if "hw2" in released:
        view["hw2"] = {"score": row["hw2"], "feedback": _feedback(db, enrollment, "HW2"), **peer("hw2")}
    if "project" in released:
        view["project"] = {
            "code": row["project_code"],
            "report": row["project_report"],
            "bonus": row["bonus_points"],
            "score": row["project_with_bonus"],
            "feedback": _feedback(db, enrollment, "PROJECT"),
            **peer("project_code"),
        }
    if "talks" in released:
        view["talks"] = {
            "presentation": row["presentation"],
            "final_talk": row["final_talk"],
            **peer("presentation"),
        }
    if "attendance" in released:
        course = db.get(Course, enrollment.course_id)
        view["attendance"] = {
            "percent": enrollment.attendance_percent,
            "threshold": course.attendance_threshold,
            "exempt": enrollment.attendance_exempt,
            "score": row["attendance_score"],
        }
    if "final" in released:
        view["final"] = {"score": row["final"]}
    return view
