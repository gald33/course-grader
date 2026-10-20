from __future__ import annotations

import json
import math
from dataclasses import dataclass

from sqlalchemy import and_, desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import (
    Artifact,
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
    "presentation": PRESENTATION_DIMENSIONS,
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


def _finite(v: float, default: float = 0.0) -> float:
    return v if isinstance(v, (int, float)) and math.isfinite(v) else default


def clamp(v: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, v))


def enforce_monotonic(points: list[float]) -> list[float]:
    """Clamp to [0, 5], pin endpoints (f(0)=0, f(5)=5), and enforce non-decreasing.

    The endpoint pin guarantees every curve spans the full grading range:
    a raw 0 always maps to 0 (no credit for nothing), a raw 5 always to 5 (full
    credit for top work). Only the middle four points are free to be reshaped
    by calibration or manual editing."""
    adjusted = [clamp(_finite(float(p)), 0, 5) for p in points]
    if adjusted:
        adjusted[0] = 0.0
        adjusted[-1] = 5.0
    for idx in range(1, len(adjusted)):
        if adjusted[idx] < adjusted[idx - 1]:
            adjusted[idx] = adjusted[idx - 1]
    return adjusted


def apply_curve(raw_score: float, points: list[float]) -> float:
    pts = enforce_monotonic(points)
    x = clamp(_finite(raw_score), 0, 5)
    left = int(x)
    right = min(5, left + 1)
    if left == right:
        return pts[left]
    fraction = x - left
    return pts[left] + fraction * (pts[right] - pts[left])


def _active_curve(db: Session, course_id: int) -> CurveRevision | None:
    return db.scalar(
        select(CurveRevision)
        .where(and_(CurveRevision.course_id == course_id, CurveRevision.is_active.is_(True)))
        .order_by(desc(CurveRevision.revision_number))
    )


def get_active_curve(db: Session, course_id: int) -> CurveRevision:
    """Return the course's active curve revision, creating the default identity
    curves on first use.

    First use can race: the course page loads several endpoints in parallel and
    each may find no revision and insert revision 1. The loser hits
    uq_curve_revision_num and returns the winner's revision instead of failing."""
    active = _active_curve(db, course_id)
    if active:
        return active

    # Creating the revision has always committed the caller's pending changes
    # (the notebook-run worker arrives here with run results unsaved). Commit
    # them on their own first, so losing the race rolls back only our insert.
    db.commit()
    curve = CurveRevision(
        course_id=course_id,
        revision_number=1,
        mapping_json=json.dumps(default_curve_mapping()),
        note="Default identity curves",
        is_active=True,
    )
    db.add(curve)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        active = _active_curve(db, course_id)
        if active is None:
            raise
        return active
    db.refresh(curve)
    return curve


def parse_curve_mapping(revision: CurveRevision) -> dict[str, dict]:
    data = json.loads(revision.mapping_json)
    return {
        k: {"points": enforce_monotonic(v["points"]), "tunable": bool(v.get("tunable", True))}
        for k, v in data.items()
        if not k.startswith("__")
    }


def parse_final_distribution(revision: CurveRevision | None) -> dict | None:
    """Read the rank-preserving target distribution stored in a curve revision, if any."""
    if revision is None:
        return None
    try:
        data = json.loads(revision.mapping_json)
    except (TypeError, ValueError):
        return None
    cfg = data.get("__final_distribution__")
    if not isinstance(cfg, dict):
        return None
    try:
        return {"mean": float(cfg["mean"]), "sigma": float(cfg["sigma"])}
    except (KeyError, TypeError, ValueError):
        return None


def parse_shared_bonus(revision: CurveRevision | None) -> float:
    """Uniform additive offset applied to every student's final score.

    Stored under `__shared_bonus__` on the curve revision when calibration can't
    reach the target with curves alone (curves capped to avoid saturation, the
    remainder closed with this bonus)."""
    if revision is None:
        return 0.0
    try:
        data = json.loads(revision.mapping_json)
    except (TypeError, ValueError):
        return 0.0
    raw = data.get("__shared_bonus__")
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def save_curve_revision(db: Session, course_id: int, mapping: dict[str, dict], note: str) -> CurveRevision:
    prior_meta: dict[str, dict] = {}
    prior = db.scalar(
        select(CurveRevision)
        .where(CurveRevision.course_id == course_id, CurveRevision.is_active.is_(True))
        .order_by(desc(CurveRevision.revision_number))
    )
    if prior is not None:
        try:
            prior_data = json.loads(prior.mapping_json)
            prior_meta = {k: v for k, v in prior_data.items() if k.startswith("__")}
        except (TypeError, ValueError):
            prior_meta = {}

    for rev in db.scalars(select(CurveRevision).where(CurveRevision.course_id == course_id, CurveRevision.is_active.is_(True))):
        rev.is_active = False

    max_rev = db.scalar(select(CurveRevision.revision_number).where(CurveRevision.course_id == course_id).order_by(desc(CurveRevision.revision_number)).limit(1))
    revision_num = int(max_rev or 0) + 1

    cleaned: dict[str, dict] = {}
    for k, v in prior_meta.items():
        if k not in mapping:
            cleaned[k] = v
    for k, v in mapping.items():
        if k.startswith("__"):
            cleaned[k] = v
        else:
            cleaned[k] = {
                "points": enforce_monotonic(v.get("points", [0, 1, 2, 3, 4, 5])),
                "tunable": bool(v.get("tunable", True)),
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
    use_curve: bool = True,
    curve_override: dict[str, dict] | None = None,
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
    if curve_override is not None:
        by_key: dict[str, float] = {}
        for row in rows:
            cfg = curve_override.get(row.dimension_key, {"points": [0, 1, 2, 3, 4, 5]})
            by_key[row.dimension_key] = apply_curve(row.raw_score, cfg["points"])
    else:
        by_key = {
            row.dimension_key: (row.adjusted_score if use_curve else row.raw_score)
            for row in rows
        }

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


def _is_report_missing(db: Session, submission: Submission) -> bool:
    if submission.missing_report_flag:
        return True
    has_report_pdf = db.scalar(
        select(Artifact.id).where(
            Artifact.submission_id == submission.id,
            Artifact.kind == "project_report_pdf",
        )
    ) is not None
    if has_report_pdf:
        return False
    has_generic_pdf = db.scalar(
        select(Artifact.id).where(
            Artifact.submission_id == submission.id,
            Artifact.kind == "submission_file",
            Artifact.filename.ilike("%.pdf"),
        )
    ) is not None
    return not has_generic_pdf


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


def compute_gradebook_rows(
    db: Session,
    course_id: int,
    include_bonus: bool = True,
    curve_override: dict[str, dict] | None = None,
) -> list[dict]:
    course = db.get(Course, course_id)
    if not course:
        return []

    shared_bonus = (
        parse_shared_bonus(get_active_curve(db, course_id)) if curve_override is None else 0.0
    )

    enrollments = db.scalars(
        select(Enrollment)
        .join(Student)
        .where(Enrollment.course_id == course_id, Enrollment.is_test.is_(False), Enrollment.withdrawn_at.is_(None))
        .order_by(Student.national_id)
    ).all()

    return [
        _gradebook_row(db, course, enrollment, shared_bonus, include_bonus, curve_override)
        for enrollment in enrollments
    ]


def compute_student_grade_row(db: Session, enrollment: Enrollment) -> dict:
    """One enrollment's gradebook row, identical to its row in
    compute_gradebook_rows. Works for test students too, who are left out of
    the course gradebook."""
    course = db.get(Course, enrollment.course_id)
    shared_bonus = parse_shared_bonus(get_active_curve(db, course.id))
    return _gradebook_row(db, course, enrollment, shared_bonus, True, None)


def _gradebook_row(
    db: Session,
    course: Course,
    enrollment: Enrollment,
    shared_bonus: float,
    include_bonus: bool,
    curve_override: dict[str, dict] | None,
) -> dict:
    course_id = course.id
    student = enrollment.student
    hw1_submission = _get_submission_for_student(db, course_id, student.id, "HW1")
    hw2_submission = _get_submission_for_student(db, course_id, student.id, "HW2")
    project_submission = _get_submission_for_student(db, course_id, student.id, "PROJECT")

    attendance_score = 100.0 if enrollment.attendance_exempt else (100.0 if (enrollment.attendance_percent or 0.0) >= course.attendance_threshold else 0.0)

    hw1 = 100.0 if hw1_submission else 0.0
    if hw1_submission and hw1_submission.manual_grade is not None:
        hw1 = float(hw1_submission.manual_grade)

    hw2_penalty = _penalty_for_submission(db, hw2_submission)
    hw2 = (
        component_score_from_rubric(db, hw2_submission.id, "hw2_code", hw2_penalty, curve_override=curve_override)
        if hw2_submission
        else 0.0
    )
    hw2_uncurved = (
        component_score_from_rubric(db, hw2_submission.id, "hw2_code", hw2_penalty, use_curve=False)
        if hw2_submission
        else 0.0
    )
    if hw2_submission and hw2_submission.manual_grade is not None:
        hw2 = float(hw2_submission.manual_grade)
        hw2_uncurved = float(hw2_submission.manual_grade)

    project_penalty = _penalty_for_submission(db, project_submission)
    project_code = (
        component_score_from_rubric(db, project_submission.id, "project_code", project_penalty, curve_override=curve_override)
        if project_submission
        else 0.0
    )
    project_code_uncurved = (
        component_score_from_rubric(db, project_submission.id, "project_code", project_penalty, use_curve=False)
        if project_submission
        else 0.0
    )
    project_report = (
        component_score_from_rubric(db, project_submission.id, "project_report", 1.0, curve_override=curve_override)
        if project_submission
        else 0.0
    )
    project_report_uncurved = (
        component_score_from_rubric(db, project_submission.id, "project_report", 1.0, use_curve=False)
        if project_submission
        else 0.0
    )
    if project_submission and _is_report_missing(db, project_submission):
        project_report = 0.0
        project_report_uncurved = 0.0

    presentation_row = db.scalar(
        select(PresentationScore).where(
            PresentationScore.course_id == course_id,
            PresentationScore.student_id == student.id,
            PresentationScore.stage == "presentation",
        )
    )
    final_row = db.scalar(
        select(PresentationScore).where(
            PresentationScore.course_id == course_id,
            PresentationScore.student_id == student.id,
            PresentationScore.stage == "final",
        )
    )

    presentation = _presentation_score_percent(presentation_row)
    final_talk = _presentation_score_percent(final_row)
    presentation_uncurved = presentation
    final_talk_uncurved = final_talk

    if project_submission and presentation == 0:
        presentation = component_score_from_rubric(
            db, project_submission.id, "presentation", 1.0, curve_override=curve_override
        )
        presentation_uncurved = component_score_from_rubric(
            db, project_submission.id, "presentation", 1.0, use_curve=False
        )
    if project_submission and final_talk == 0:
        final_talk = component_score_from_rubric(
            db, project_submission.id, "final_talk", 1.0, curve_override=curve_override
        )
        final_talk_uncurved = component_score_from_rubric(
            db, project_submission.id, "final_talk", 1.0, use_curve=False
        )

    overrides = _overrides_for_student(db, course_id, student.id)

    hw1 += overrides.get("hw1", 0.0)
    hw2 += overrides.get("hw2", 0.0)
    hw2_uncurved += overrides.get("hw2", 0.0)
    project_code += overrides.get("project_code", 0.0)
    project_code_uncurved += overrides.get("project_code", 0.0)
    project_report += overrides.get("project_report", 0.0)
    project_report_uncurved += overrides.get("project_report", 0.0)
    presentation += overrides.get("presentation", 0.0)
    presentation_uncurved += overrides.get("presentation", 0.0)
    final_talk += overrides.get("final_talk", 0.0)
    final_talk_uncurved += overrides.get("final_talk", 0.0)
    attendance_score += overrides.get("attendance", 0.0)

    project_base = (0.60 * project_code) + (0.20 * project_report) + (0.20 * presentation)
    project_base_uncurved = (
        (0.60 * project_code_uncurved)
        + (0.20 * project_report_uncurved)
        + (0.20 * presentation_uncurved)
    )
    if project_submission and project_submission.manual_grade is not None:
        project_base = float(project_submission.manual_grade)
        project_base_uncurved = float(project_submission.manual_grade)
    bonus_points = overrides.get("bonus", 0.0)
    if not include_bonus:
        bonus_points = 0.0
    project_with_bonus = project_base + bonus_points
    project_with_bonus_uncurved = project_base_uncurved + bonus_points

    final_score = _finite(
        (0.10 * hw1) + (0.10 * hw2) + (0.70 * project_with_bonus) + (0.10 * attendance_score)
    )
    if shared_bonus:
        final_score = clamp(final_score + shared_bonus, 0.0, 100.0)
    final_score_uncurved = _finite(
        (0.10 * hw1)
        + (0.10 * hw2_uncurved)
        + (0.70 * project_with_bonus_uncurved)
        + (0.10 * attendance_score)
    )

    return {
        "enrollment_id": enrollment.id,
        "student_id": student.id,
        "national_id": student.national_id,
        "name": student.name,
        "attendance_exempt": enrollment.attendance_exempt,
        "attendance_percent": enrollment.attendance_percent,
        "attendance_score": round(_finite(attendance_score), 2),
        "hw1": round(_finite(hw1), 2),
        "hw2": round(_finite(hw2), 2),
        "project_code": round(_finite(project_code), 2),
        "project_report": round(_finite(project_report), 2),
        "presentation": round(_finite(presentation), 2),
        "final_talk": round(_finite(final_talk), 2),
        "project_base": round(_finite(project_base), 2),
        "bonus_points": round(_finite(bonus_points), 2),
        "project_with_bonus": round(_finite(project_with_bonus), 2),
        "final": round(final_score),
        "final_uncurved": round(final_score_uncurved),
        "overrides": overrides,
    }


def _constant_delta_slope_curve(first_slope: float) -> list[float]:
    """6-point curve f(0..5) with f(0)=0, f(5)=5, and constant change in slope.

    With slopes s_i = f(i+1) - f(i) for i in 0..4, the constraint Δs_i = c
    constant plus the endpoint constraint Σs_i = 5 leaves one free parameter
    (`first_slope` = s_0). The common Δ is then c = (1 - s_0) / 2.

    - first_slope = 1.0 → identity curve (c=0, all slopes equal 1).
    - first_slope < 1   → convex (slopes grow), penalises low scorers.
    - first_slope > 1   → concave (slopes shrink), lifts low scorers.

    Valid range is [0, 2] so the trailing slope s_4 = 2 - first_slope stays
    non-negative (curve weakly monotone)."""
    s0 = clamp(first_slope, 0.0, 2.0)
    c = (1.0 - s0) / 2.0
    points = [0.0]
    for i in range(5):
        slope_i = s0 + i * c
        points.append(points[-1] + slope_i)
    return enforce_monotonic(points)


def collect_raw_scores_per_dimension(db: Session, course_id: int) -> dict[str, list[float]]:
    """For each dimension_key used in the course, return the raw_score list across all
    rubric scores in any submission of the course. Used by the curve editor to show
    each dimension's empirical input distribution next to its curve."""
    rows = db.scalars(
        select(RubricDimensionScore)
        .join(Submission, RubricDimensionScore.submission_id == Submission.id)
        .where(Submission.course_id == course_id)
    ).all()
    out: dict[str, list[float]] = {}
    for r in rows:
        out.setdefault(r.dimension_key, []).append(float(r.raw_score))
    return out


def calibrate_curves_to_mean(
    db: Session,
    course_id: int,
    target_mean: float = 83.0,
    target_sigma: float = 12.0,
    max_iterations: int = 30,
    tolerance: float = 0.25,
) -> CurveRevision:
    """Fit a single-parameter curve (constant Δslope, f(0)=0, f(5)=5) shared
    across all tunable dimensions, with optional shared bonus to close any
    residual gap.

    A binary search varies `first_slope` ∈ [0, 2]:
        first_slope = 0 → fully convex (slopes [0, 0.5, 1, 1.5, 2])
        first_slope = 1 → identity (all slopes 1)
        first_slope = 2 → fully concave (slopes [2, 1.5, 1, 0.5, 0])
    Lower first_slope penalises low scorers; higher lifts them. Locked
    dimensions keep their existing curve. The total final mean is whatever
    the rubric → curve → component → weighted-sum pipeline produces, with
    no remap. If curves alone can't reach the target a clamping-aware bonus
    is added uniformly. Per-student rank can shift since dimensional weights
    and penalties differ; the curves themselves stay weakly monotone."""
    active = parse_curve_mapping(get_active_curve(db, course_id))

    def build_mapping(first_slope: float) -> dict[str, dict]:
        curve_pts = _constant_delta_slope_curve(first_slope)
        m: dict[str, dict] = {}
        for key, cfg in active.items():
            if not cfg.get("tunable", True):
                m[key] = {"points": list(cfg["points"]), "tunable": False}
            else:
                m[key] = {"points": list(curve_pts), "tunable": True}
        return m

    def evaluate(first_slope: float) -> float:
        rows = compute_gradebook_rows(
            db, course_id, include_bonus=True, curve_override=build_mapping(first_slope)
        )
        return sum(r["final"] for r in rows) / len(rows) if rows else 0.0

    lo, hi = 0.0, 2.0
    best_slope = 1.0
    achieved = 0.0
    for _ in range(max_iterations):
        mid = (lo + hi) / 2
        achieved = evaluate(mid)
        best_slope = mid
        if abs(achieved - target_mean) <= tolerance:
            break
        if achieved < target_mean:
            # Concave (s_0 > 1) lifts the mean — search the upper half.
            lo = mid
        else:
            hi = mid

    # If curves alone leave a gap, close it with a uniform additive bonus.
    # The search honours the [0, 100] clamp so the achieved mean lands on target
    # even when many students would otherwise overflow.
    final_mapping = build_mapping(best_slope)
    base_rows = compute_gradebook_rows(
        db, course_id, include_bonus=True, curve_override=final_mapping
    )
    base_finals = [r["final"] for r in base_rows]

    shared_bonus = 0.0
    final_mean = achieved
    if base_finals and achieved < target_mean - tolerance:
        lo_b, hi_b = 0.0, 100.0
        for _ in range(50):
            mid_b = (lo_b + hi_b) / 2
            mean_with_b = sum(clamp(f + mid_b, 0.0, 100.0) for f in base_finals) / len(base_finals)
            shared_bonus = mid_b
            if abs(mean_with_b - target_mean) < 0.05:
                break
            if mean_with_b < target_mean:
                lo_b = mid_b
            else:
                hi_b = mid_b
        shared_bonus = round(shared_bonus, 2)
        final_mean = sum(clamp(f + shared_bonus, 0.0, 100.0) for f in base_finals) / len(base_finals)

    final_mapping["__final_distribution__"] = {
        "mean": float(target_mean),
        "sigma": max(float(target_sigma), 1e-6),
    }
    final_mapping["__shared_bonus__"] = shared_bonus

    note = (
        f"Fit grades target μ={target_mean:g} σ={target_sigma:g} "
        f"(curves → {achieved:.2f}"
        + (f", +{shared_bonus:g} bonus → {final_mean:.2f}" if shared_bonus > 0 else "")
        + f"; first slope={best_slope:.2f})"
    )
    rev = save_curve_revision(db, course_id, final_mapping, note)

    submission_ids = [sid for sid in db.scalars(select(Submission.id).where(Submission.course_id == course_id)).all()]
    for sid in submission_ids:
        recalculate_submission_adjusted_scores(db, course_id, sid)
    return rev
