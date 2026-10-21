"""The course's assignments as a student sees them, one entry per assignment,
for the assignment pages (/r/<token>/assignments/<id>).

What is always shown: the assignment's name and type, whether the student
has a submission on it (and when the system recorded it), and the fixed
rubric the gradebook scores it with: each dimension and the points it is
worth, never a score.

What waits for release: everything scored. An assignment's `result` is
filled only while its gradebook component (HW1 -> hw1, HW2 -> hw2,
PROJECT -> project) is released, under the same rules as grades_view, and
disappears again when the instructor un-releases it. The total score comes
from the same gradebook row as the Grades tab, and only on the submission
the gradebook counts for that type."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.entities import Assignment, Enrollment, RubricDimensionScore, Submission, SubmissionMember
from app.services.scoring import (
    COMPONENT_DIMENSIONS,
    _get_submission_for_student,
    _is_report_missing,
    _penalty_for_submission,
    compute_student_grade_row,
)
from app.services.student_grades import released_components

# The grade-release component that releases each assignment type.
RELEASE_COMPONENT = {"HW1": "hw1", "HW2": "hw2", "PROJECT": "project"}
# The fixed rubric components each type is scored on. The project's
# presentation parts are graded (and released) as talks, not here.
RUBRIC_COMPONENTS = {"HW1": (), "HW2": ("hw2_code",), "PROJECT": ("project_code", "project_report")}
# The gradebook task holding a type's peer-round part and delta overrides.
GRADEBOOK_TASK = {"HW1": "hw1", "HW2": "hw2", "PROJECT": "project_code"}
CODE_COMPONENTS = {"hw2_code", "project_code"}


def _iso(dt: datetime | None) -> str | None:
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if dt else None


def _points(weight: float) -> float:
    return round(weight * 100, 2)


def _rubric(assignment_type: str) -> list[dict]:
    return [
        {
            "key": component,
            "max": 100.0,
            "dimensions": [{"key": d.key, "max": _points(d.weight)} for d in COMPONENT_DIMENSIONS[component]],
        }
        for component in RUBRIC_COMPONENTS.get(assignment_type, ())
    ]


def _own_submission(db: Session, assignment_id: int, student_id: int) -> Submission | None:
    return db.scalar(
        select(Submission)
        .join(SubmissionMember, SubmissionMember.submission_id == Submission.id)
        .where(Submission.assignment_id == assignment_id, SubmissionMember.student_id == student_id)
        .order_by(desc(Submission.id))
    )


def _explanations(submission: Submission) -> dict[str, dict[str, dict]]:
    """The graders' stored per-dimension explanations, by component:
    code_review_json (notebook runs) and project_llm_review_json (report)."""
    out: dict[str, dict[str, dict]] = {}
    for raw, default_component in ((submission.code_review_json, None), (submission.project_llm_review_json, "project_report")):
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            continue
        if not isinstance(data, dict) or not isinstance(data.get("dimensions"), dict):
            continue
        component = data.get("component") or default_component
        if component:
            out[component] = {k: v for k, v in data["dimensions"].items() if isinstance(v, dict)}
    return out


def _rationale(explanation: dict | None, row: RubricDimensionScore) -> str:
    # A rationale explains the score it was written for: once the grader
    # changes that score, it no longer applies and is left out.
    if not explanation or not isinstance(explanation.get("score"), (int, float)):
        return ""
    if abs(float(explanation["score"]) - row.raw_score) > 1e-9:
        return ""
    return str(explanation.get("rationale") or "").strip()


def _breakdown(db: Session, submission: Submission, assignment_type: str) -> list[dict]:
    """Per component, each dimension's points as the gradebook counts them
    (the curved score, out of the dimension's weight), the component's
    subtotal, and the run-ratio multiplier on code components."""
    rows = {
        (r.component, r.dimension_key): r
        for r in db.scalars(select(RubricDimensionScore).where(RubricDimensionScore.submission_id == submission.id))
    }
    explanations = _explanations(submission)
    out = []
    for component in RUBRIC_COMPONENTS.get(assignment_type, ()):
        missing = component == "project_report" and _is_report_missing(db, submission)
        multiplier = _penalty_for_submission(db, submission) if component in CODE_COMPONENTS else 1.0
        dims = []
        total = 0.0
        for d in COMPONENT_DIMENSIONS[component]:
            row = rows.get((component, d.key))
            score = None if row is None or missing else round(row.adjusted_score / 5.0 * 100.0 * d.weight, 2)
            total += score or 0.0
            dims.append(
                {
                    "key": d.key,
                    "max": _points(d.weight),
                    "score": score,
                    "rationale": "" if row is None or missing else _rationale(explanations.get(component, {}).get(d.key), row),
                }
            )
        out.append(
            {
                "key": component,
                "max": 100.0,
                "multiplier": round(multiplier, 4),
                "missing": missing,
                "subtotal": 0.0 if missing else round(total * multiplier, 2),
                "dimensions": dims,
            }
        )
    return out


def assignments_view(db: Session, enrollment: Enrollment) -> list[dict]:
    released = released_components(db, enrollment.course_id)
    assignments = db.scalars(
        select(Assignment)
        .where(Assignment.course_id == enrollment.course_id)
        .order_by(Assignment.assignment_type, Assignment.workcode)
    ).all()
    counted: dict[str, int] = {}
    for assignment_type in RELEASE_COMPONENT:
        sub = _get_submission_for_student(db, enrollment.course_id, enrollment.student_id, assignment_type)
        if sub is not None:
            counted[assignment_type] = sub.id
    # Computed once, and only when something is released (as grades_view).
    any_released = any(RELEASE_COMPONENT.get(a.assignment_type) in released for a in assignments)
    row = compute_student_grade_row(db, enrollment) if any_released else None

    out = []
    for a in assignments:
        submission = _own_submission(db, a.id, enrollment.student_id)
        is_released = RELEASE_COMPONENT.get(a.assignment_type) in released
        counts = submission is not None and counted.get(a.assignment_type) == submission.id
        entry: dict = {
            "id": a.id,
            "name": a.name,
            "assignment_type": a.assignment_type,
            "workcode": a.workcode,
            "submission": {"recorded_at": _iso(submission.created_at)} if submission else None,
            "counts": counts,
            "released": is_released,
            "rubric": _rubric(a.assignment_type),
            "result": None,
        }
        if is_released and submission is not None and row is not None:
            task = GRADEBOOK_TASK[a.assignment_type]
            peer = row["peer"].get(task)
            result: dict = {
                "manual": submission.manual_grade is not None,
                "components": [] if submission.manual_grade is not None else _breakdown(db, submission, a.assignment_type),
                "feedback": (submission.feedback_student or "").strip(),
                "score": None,
                "peer": None,
                "adjustment": None,
            }
            # The total, peer part and adjustments belong to the gradebook's
            # counted submission only; another submission of the same type
            # does not enter the grade.
            if counts:
                if a.assignment_type == "PROJECT":
                    result["score"] = row["project_with_bonus"]
                    result["project"] = {
                        "code": row["project_code"],
                        "report": row["project_report"],
                        # Graded and released as talks.
                        "presentation": row["presentation"] if "talks" in released else None,
                        "bonus": row["bonus_points"],
                    }
                else:
                    result["score"] = row[task]
                if peer is not None:
                    result["peer"] = {
                        "rounds": peer["rounds"],
                        "weight": round(peer["weight"], 4),
                        "peer": round(peer["peer"], 2),
                        "auto": peer.get("auto"),
                    }
                delta = row["overrides"].get(task, 0.0)
                result["adjustment"] = round(delta, 2) if delta else None
            entry["result"] = result
        out.append(entry)
    return out
