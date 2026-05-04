from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import (
    Assignment,
    Course,
    CurveRevision,
    Enrollment,
    NotebookRun,
    PresentationScore,
    RubricDimensionScore,
    Student,
    StudentComponentOverride,
    Submission,
    SubmissionMember,
)

settings = get_settings()


@dataclass(frozen=True)
class DimensionDef:
    key: str
    weight: float
    tunable: bool = True


CODE_DIMENSIONS: list[DimensionDef] = [
    DimensionDef("data_scope_adequacy", 0.05, tunable=True),
    DimensionDef("processing_description", 0.10, tunable=True),
    DimensionDef("processing_implementation", 0.15, tunable=True),
    DimensionDef("num_models_baseline", 0.10, tunable=True),
    DimensionDef("models_quality", 0.15, tunable=True),
    DimensionDef("experiments_comparison", 0.10, tunable=True),
    DimensionDef("variable_plots", 0.05, tunable=True),
    DimensionDef("results_plots", 0.10, tunable=True),
    DimensionDef("order", 0.04, tunable=True),
    DimensionDef("clarity", 0.04, tunable=True),
    DimensionDef("code_quality", 0.08, tunable=True),
    DimensionDef("english_comments_compliance", 0.04, tunable=False),
]

REPORT_DIMENSIONS: list[DimensionDef] = [
    DimensionDef("research_question_hypothesis", 0.15, tunable=True),
    DimensionDef("data_description", 0.15, tunable=True),
    DimensionDef("data_processing", 0.20, tunable=True),
    DimensionDef("models_comparison", 0.20, tunable=True),
    DimensionDef("results_analysis", 0.20, tunable=True),
    DimensionDef("consistency_with_code", 0.10, tunable=True),
]

PRESENTATION_DIMENSIONS: list[DimensionDef] = [
    DimensionDef("clarity", 0.30, tunable=True),
    DimensionDef("complexity", 0.20, tunable=True),
    DimensionDef("qa_answers", 0.20, tunable=True),
    DimensionDef("elegance", 0.10, tunable=True),
    DimensionDef("subjective_impression", 0.20, tunable=True),
]

COMPONENT_DIMENSIONS: dict[str, list[DimensionDef]] = {
    "hw2_code": CODE_DIMENSIONS,
    "project_code": CODE_DIMENSIONS,
    "project_report": REPORT_DIMENSIONS,
    "initial_talk": PRESENTATION_DIMENSIONS,
    "final_talk": PRESENTATION_DIMENSIONS,
}


def default_curve_mapping() -> dict[str, dict]:
    mapping: dict[str, dict] = {}
    all_defs: dict[str, bool] = {}
    for dims in COMPONENT_DIMENSIONS.values():
        for dim in dims:
            all_defs[dim.key] = all_defs.get(dim.key, False) or dim.tunable

    for key, tunable in all_defs.items():
        mapping[key] = {"points": [0, 1, 2, 3, 4, 5], "tunable": tunable}

    mapping["consistency_with_code"]["tunable"] = True
    mapping["complexity"]["tunable"] = True
    return mapping


def clamp(v: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, v))


def enforce_monotonic(points: list[float]) -> list[float]:
    adjusted = [clamp(float(p), 0, 5) for p in points]
    for idx in range(1, len(adjusted)):
        if adjusted[idx] < adjusted[idx - 1]:
            adjusted[idx] = adjusted[idx - 1]
    return adjusted


def apply_curve(raw_score: float, points: list[float]) -> float:
    pts = enforce_monotonic(points)
    x = clamp(raw_score, 0, 5)
    left = int(x)
    right = min(5, left + 1)
    if left == right:
        return pts[left]
    fraction = x - left
    return pts[left] + fraction * (pts[right] - pts[left])


def get_active_curve(db: Session, course_id: int) -> CurveRevision:
    active = db.scalar(
        select(CurveRevision)
        .where(and_(CurveRevision.course_id == course_id, CurveRevision.is_active.is_(True)))
        .order_by(desc(CurveRevision.revision_number))
    )
    if active:
        return active

    curve = CurveRevision(
        course_id=course_id,
        revision_number=1,
        mapping_json=json.dumps(default_curve_mapping()),
        note="Default identity curves",
        is_active=True,
    )
    db.add(curve)
    db.commit()
    db.refresh(curve)
    return curve


def parse_curve_mapping(revision: CurveRevision) -> dict[str, dict]:
    data = json.loads(revision.mapping_json)
    return {k: {"points": enforce_monotonic(v["points"]), "tunable": bool(v.get("tunable", True))} for k, v in data.items()}


def save_curve_revision(db: Session, course_id: int, mapping: dict[str, dict], note: str) -> CurveRevision:
    for rev in db.scalars(select(CurveRevision).where(CurveRevision.course_id == course_id, CurveRevision.is_active.is_(True))):
        rev.is_active = False

    max_rev = db.scalar(select(CurveRevision.revision_number).where(CurveRevision.course_id == course_id).order_by(desc(CurveRevision.revision_number)).limit(1))
    revision_num = int(max_rev or 0) + 1

    cleaned = {
        k: {
            "points": enforce_monotonic(v.get("points", [0, 1, 2, 3, 4, 5])),
            "tunable": bool(v.get("tunable", True)),
        }
        for k, v in mapping.items()
    }
    rev = CurveRevision(
        course_id=course_id,
        revision_number=revision_num,
        mapping_json=json.dumps(cleaned),
        note=note,
        is_active=True,
    )
    db.add(rev)
    db.commit()
    db.refresh(rev)
    return rev


def recalculate_submission_adjusted_scores(db: Session, course_id: int, submission_id: int) -> None:
    curve = parse_curve_mapping(get_active_curve(db, course_id))
    rows = db.scalars(select(RubricDimensionScore).where(RubricDimensionScore.submission_id == submission_id)).all()
    for row in rows:
        cfg = curve.get(row.dimension_key, {"points": [0, 1, 2, 3, 4, 5]})
        row.adjusted_score = round(apply_curve(row.raw_score, cfg["points"]), 4)
    db.commit()


def component_score_from_rubric(
    db: Session,
    submission_id: int,
    component: str,
    penalty_multiplier: float = 1.0,
) -> float:
    dims = COMPONENT_DIMENSIONS.get(component, [])
    if not dims:
        return 0.0

    rows = db.scalars(
        select(RubricDimensionScore).where(
            RubricDimensionScore.submission_id == submission_id,
            RubricDimensionScore.component == component,
        )
    ).all()
    by_key = {row.dimension_key: row.adjusted_score for row in rows}

    weighted = 0.0
    for dim in dims:
        weighted += (by_key.get(dim.key, 0.0) / 5.0) * 100.0 * dim.weight

    if component in {"hw2_code", "project_code"}:
        weighted *= penalty_multiplier
    return round(weighted, 2)


def _get_submission_for_student(db: Session, course_id: int, student_id: int, assignment_type: str) -> Submission | None:
    stmt = (
        select(Submission)
        .join(SubmissionMember, Submission.id == SubmissionMember.submission_id)
        .join(Assignment, Submission.assignment_id == Assignment.id)
        .where(
            Submission.course_id == course_id,
            SubmissionMember.student_id == student_id,
            Assignment.assignment_type == assignment_type,
        )
        .order_by(desc(Assignment.workcode), desc(Submission.id))
    )
    return db.scalar(stmt)


def _penalty_for_submission(db: Session, submission: Submission | None) -> float:
    if submission is None:
        return 1.0

    run = None
    if submission.pinned_run_id:
        run = db.scalar(select(NotebookRun).where(NotebookRun.id == submission.pinned_run_id))
    if run is None:
        run = db.scalar(
            select(NotebookRun)
            .where(NotebookRun.submission_id == submission.id, NotebookRun.status.in_(["SUCCESS", "FAILED", "TIMEOUT"]))
            .order_by(desc(NotebookRun.id))
        )
    if run is None:
        return 1.0
    return run.penalty_multiplier or 0.0


def _presentation_score_percent(row: PresentationScore | None) -> float:
    if row is None:
        return 0.0
    return round(
        ((row.clarity / 5) * 100 * 0.30)
        + ((row.complexity / 5) * 100 * 0.20)
        + ((row.qa_answers / 5) * 100 * 0.20)
        + ((row.elegance / 5) * 100 * 0.10)
        + ((row.subjective_impression / 5) * 100 * 0.20),
        2,
    )


def _overrides_for_student(db: Session, course_id: int, student_id: int) -> dict[str, float]:
    rows = db.scalars(
        select(StudentComponentOverride).where(
            StudentComponentOverride.course_id == course_id,
            StudentComponentOverride.student_id == student_id,
        )
    ).all()
    merged: dict[str, float] = {}
    for row in rows:
        merged[row.component] = merged.get(row.component, 0.0) + row.delta
    return merged


def compute_gradebook_rows(db: Session, course_id: int, include_bonus: bool = True) -> list[dict]:
    course = db.get(Course, course_id)
    if not course:
        return []

    enrollments = db.scalars(
        select(Enrollment).join(Student).where(Enrollment.course_id == course_id).order_by(Student.national_id)
    ).all()

    output: list[dict] = []
    for enrollment in enrollments:
        student = enrollment.student
        hw1_submission = _get_submission_for_student(db, course_id, student.id, "HW1")
        hw2_submission = _get_submission_for_student(db, course_id, student.id, "HW2")
        project_submission = _get_submission_for_student(db, course_id, student.id, "PROJECT")

        attendance_score = 100.0 if enrollment.attendance_exempt else (100.0 if (enrollment.attendance_percent or 0.0) >= course.attendance_threshold else 0.0)

        hw1 = 100.0 if hw1_submission else 0.0
        if hw1_submission and hw1_submission.manual_grade is not None:
            hw1 = float(hw1_submission.manual_grade)

        hw2_penalty = _penalty_for_submission(db, hw2_submission)
        hw2 = component_score_from_rubric(db, hw2_submission.id, "hw2_code", hw2_penalty) if hw2_submission else 0.0
        if hw2_submission and hw2_submission.manual_grade is not None:
            hw2 = float(hw2_submission.manual_grade)

        project_penalty = _penalty_for_submission(db, project_submission)
        project_code = component_score_from_rubric(db, project_submission.id, "project_code", project_penalty) if project_submission else 0.0
        project_report = component_score_from_rubric(db, project_submission.id, "project_report", 1.0) if project_submission else 0.0

        initial_row = db.scalar(
            select(PresentationScore).where(
                PresentationScore.course_id == course_id,
                PresentationScore.student_id == student.id,
                PresentationScore.stage == "initial",
            )
        )
        final_row = db.scalar(
            select(PresentationScore).where(
                PresentationScore.course_id == course_id,
                PresentationScore.student_id == student.id,
                PresentationScore.stage == "final",
            )
        )

        initial_talk = _presentation_score_percent(initial_row)
        final_talk = _presentation_score_percent(final_row)

        if project_submission and initial_talk == 0:
            initial_talk = component_score_from_rubric(db, project_submission.id, "initial_talk", 1.0)
        if project_submission and final_talk == 0:
            final_talk = component_score_from_rubric(db, project_submission.id, "final_talk", 1.0)

        overrides = _overrides_for_student(db, course_id, student.id)

        hw1 += overrides.get("hw1", 0.0)
        hw2 += overrides.get("hw2", 0.0)
        project_code += overrides.get("project_code", 0.0)
        project_report += overrides.get("project_report", 0.0)
        initial_talk += overrides.get("initial_talk", 0.0)
        final_talk += overrides.get("final_talk", 0.0)
        attendance_score += overrides.get("attendance", 0.0)

        project_base = (0.50 * project_code) + (0.20 * project_report) + (0.10 * initial_talk) + (0.20 * final_talk)
        if project_submission and project_submission.manual_grade is not None:
            project_base = float(project_submission.manual_grade)
        bonus_points = enrollment.bonus_points + overrides.get("bonus", 0.0)
        if not include_bonus:
            bonus_points = 0.0
        project_with_bonus = project_base + bonus_points

        final_score = (0.10 * hw1) + (0.10 * hw2) + (0.70 * project_with_bonus) + (0.10 * attendance_score)

        output.append(
            {
                "enrollment_id": enrollment.id,
                "student_id": student.id,
                "national_id": student.national_id,
                "name": student.name,
                "attendance_exempt": enrollment.attendance_exempt,
                "attendance_percent": enrollment.attendance_percent,
                "attendance_score": round(attendance_score, 2),
                "hw1": round(hw1, 2),
                "hw2": round(hw2, 2),
                "project_code": round(project_code, 2),
                "project_report": round(project_report, 2),
                "initial_talk": round(initial_talk, 2),
                "final_talk": round(final_talk, 2),
                "project_base": round(project_base, 2),
                "bonus_points": round(bonus_points, 2),
                "project_with_bonus": round(project_with_bonus, 2),
                "final": round(final_score, 2),
                "overrides": overrides,
            }
        )

    return output


def calibrate_curves_to_mean(
    db: Session,
    course_id: int,
    target_mean: float = 83.0,
    note: str = "Calibration to mean 83",
) -> CurveRevision:
    base_rows = compute_gradebook_rows(db, course_id, include_bonus=False)
    current_mean = sum(r["final"] for r in base_rows) / len(base_rows) if base_rows else 0.0

    active = parse_curve_mapping(get_active_curve(db, course_id))
    if current_mean <= 0:
        return save_curve_revision(db, course_id, active, note)

    factor = target_mean / current_mean

    new_mapping: dict[str, dict] = {}
    for key, cfg in active.items():
        points = list(cfg["points"])
        if cfg.get("tunable", True):
            scaled = [clamp(p * factor, 0, 5) for p in points]
            points = enforce_monotonic(scaled)
        new_mapping[key] = {"points": points, "tunable": cfg.get("tunable", True)}

    rev = save_curve_revision(db, course_id, new_mapping, note)

    submission_ids = [sid for sid in db.scalars(select(Submission.id).where(Submission.course_id == course_id)).all()]
    for sid in submission_ids:
        recalculate_submission_adjusted_scores(db, course_id, sid)
    return rev
