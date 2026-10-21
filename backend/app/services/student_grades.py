"""What a student sees of their own grade: only the gradebook components the
instructor has released, plus the instructor's feedback text on the
submissions those components grade."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Assignment, Course, Enrollment, GradeRelease, Submission, SubmissionMember
from app.services import custom_rubrics
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


# The grade-release component that releases each autograded assignment type.
RUBRIC_RELEASE_COMPONENT = {"HW2": "hw2", "PROJECT": "project"}


def rubrics_view(db: Session, enrollment: Enrollment) -> list[dict]:
    """The custom rubrics of the course's assignments, for the student page.

    Each criterion's name, description and max points are always shown, so
    students know what they are graded on. Scores, rationales and the
    instructor's feedback appear only once the assignment's gradebook
    component is released, under the same rules as grades_view. An
    overridden criterion carries no rationale (it was written for the LLM's
    score, not the instructor's). `counts` marks the assignment whose
    submission the gradebook counts for that type."""
    released = released_components(db, enrollment.course_id)
    assignments = db.scalars(
        select(Assignment)
        .where(
            Assignment.course_id == enrollment.course_id,
            Assignment.assignment_type.in_(RUBRIC_RELEASE_COMPONENT),
        )
        .order_by(Assignment.assignment_type, Assignment.workcode)
    ).all()
    counted = set()
    for assignment_type in RUBRIC_RELEASE_COMPONENT:
        sub = _get_submission_for_student(db, enrollment.course_id, enrollment.student_id, assignment_type)
        if sub is not None:
            counted.add(sub.assignment_id)
    out: list[dict] = []
    for assignment in assignments:
        rubric = custom_rubrics.get_rubric(db, assignment.id)
        if rubric is None or not rubric.criteria:
            continue
        entry: dict = {
            "assignment_id": assignment.id,
            "name": assignment.name,
            "assignment_type": assignment.assignment_type,
            "released": RUBRIC_RELEASE_COMPONENT[assignment.assignment_type] in released,
            "counts": assignment.id in counted,
            "criteria": [
                {"name": c.name, "description": c.description, "max_points": c.max_points} for c in rubric.criteria
            ],
        }
        if entry["released"]:
            submission = db.scalar(
                select(Submission)
                .join(SubmissionMember, SubmissionMember.submission_id == Submission.id)
                .where(Submission.assignment_id == assignment.id, SubmissionMember.student_id == enrollment.student_id)
                .order_by(Submission.id.desc())
            )
            breakdown = custom_rubrics.submission_breakdown(db, submission) if submission else None
            scored = {c["id"]: c for c in breakdown["criteria"]} if breakdown else {}
            for item, criterion in zip(entry["criteria"], rubric.criteria):
                result = scored.get(criterion.id)
                item["score"] = result["effective_score"] if result else None
                item["rationale"] = (
                    result["rationale"] if result and result["status"] == "scored" and result["source"] == "llm" else ""
                )
            entry["total"] = breakdown["total"] if breakdown else None
            entry["max_total"] = round(sum(c.max_points for c in rubric.criteria), 4)
            entry["feedback"] = (submission.feedback_student or "").strip() if submission else ""
        out.append(entry)
    return out

