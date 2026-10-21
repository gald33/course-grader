"""Custom rubrics: authoring, the autograder's per-criterion scoring, and the
score each criterion counts for in the gradebook.

An assignment with a rubric is graded on its criteria: the effective score
of a criterion is the instructor's override if there is one, else the
autograder's latest scored result. Its gradebook component is the sum of
effective scores over the sum of maxima, as a percentage, times the
run-ratio penalty. Assignments without a rubric never reach this module's
scoring paths.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.entities import (
    Artifact,
    Assignment,
    AssignmentRubric,
    CriterionOverride,
    CriterionResult,
    NotebookRun,
    RubricCriterion,
    Submission,
)

logger = logging.getLogger(__name__)

# Assignment types the autograder runs notebooks for, and so can score.
RUBRIC_ASSIGNMENT_TYPES = {"HW2", "PROJECT"}

SCORED = "scored"
NOT_SCORED = "not_scored"


# ---------------------------------------------------------------------------
# Authoring
# ---------------------------------------------------------------------------


def get_rubric(db: Session, assignment_id: int) -> AssignmentRubric | None:
    return db.scalar(select(AssignmentRubric).where(AssignmentRubric.assignment_id == assignment_id))


def criterion_levels(criterion: RubricCriterion) -> list[dict[str, Any]]:
    try:
        levels = json.loads(criterion.levels_json or "[]")
    except (TypeError, ValueError):
        return []
    return levels if isinstance(levels, list) else []


def serialize_criterion(c: RubricCriterion) -> dict[str, Any]:
    return {
        "id": c.id,
        "position": c.position,
        "name": c.name,
        "description": c.description,
        "max_points": c.max_points,
        "levels": criterion_levels(c),
    }


def serialize_rubric(db: Session, rubric: AssignmentRubric | None) -> dict[str, Any] | None:
    if rubric is None:
        return None
    copied_from = None
    if rubric.copied_from_rubric_id is not None:
        source = db.get(AssignmentRubric, rubric.copied_from_rubric_id)
        source_assignment = db.get(Assignment, source.assignment_id) if source else None
        if source_assignment is not None:
            copied_from = {"assignment_id": source_assignment.id, "name": source_assignment.name}
    criteria = [serialize_criterion(c) for c in rubric.criteria]
    return {
        "id": rubric.id,
        "assignment_id": rubric.assignment_id,
        "criteria": criteria,
        "total_points": round(sum(c["max_points"] for c in criteria), 4),
        "copied_from": copied_from,
        "updated_at": rubric.updated_at,
    }


def _delete_criterion_rows(db: Session, criterion_ids: list[int]) -> None:
    """Results and overrides of criteria about to be deleted. Explicit, since
    SQLite does not enforce the ON DELETE CASCADE foreign keys."""
    if criterion_ids:
        for model in (CriterionResult, CriterionOverride):
            db.execute(delete(model).where(model.criterion_id.in_(criterion_ids)))


def save_criteria(db: Session, assignment: Assignment, criteria: list[dict[str, Any]]) -> AssignmentRubric:
    """Make the assignment's rubric exactly `criteria`, in that order.

    A criterion carrying the id of one of this rubric's criteria is edited in
    place (its results and overrides stay); one without an id is created;
    existing criteria left out are deleted with their results and overrides.
    Raises ValueError for an id from another rubric. Commits."""
    rubric = get_rubric(db, assignment.id)
    if rubric is None:
        rubric = AssignmentRubric(assignment_id=assignment.id)
        db.add(rubric)
        db.flush()

    existing = {c.id: c for c in rubric.criteria}
    kept: set[int] = set()
    for position, item in enumerate(criteria):
        cid = item.get("id")
        if cid is not None:
            if cid not in existing:
                raise ValueError(f"Criterion {cid} is not part of this rubric")
            row = existing[cid]
            kept.add(cid)
        else:
            row = RubricCriterion(rubric_id=rubric.id)
            rubric.criteria.append(row)
        row.position = position
        row.name = item["name"]
        row.description = item.get("description", "")
        row.max_points = float(item["max_points"])
        row.levels_json = json.dumps(item.get("levels") or [], ensure_ascii=False)
    removed = [cid for cid in existing if cid not in kept]
    _delete_criterion_rows(db, removed)
    for cid in removed:
        row = existing[cid]
        rubric.criteria.remove(row)
        db.delete(row)
    rubric.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(rubric)
    return rubric


def copy_rubric(db: Session, target: Assignment, source: AssignmentRubric) -> AssignmentRubric:
    """Replace the target's rubric with a copy of `source`'s criteria. Commits."""
    criteria = [
        {
            "name": c.name,
            "description": c.description,
            "max_points": c.max_points,
            "levels": criterion_levels(c),
        }
        for c in source.criteria
    ]
    delete_rubric(db, target.id)
    rubric = save_criteria(db, target, criteria)
    rubric.copied_from_rubric_id = source.id
    db.commit()
    db.refresh(rubric)
    return rubric


def delete_rubric(db: Session, assignment_id: int) -> bool:
    """Remove the rubric (and its results and overrides): the assignment goes
    back to the fixed code dimensions. Commits."""
    rubric = get_rubric(db, assignment_id)
    if rubric is None:
        return False
    _delete_criterion_rows(db, [c.id for c in rubric.criteria])
    db.execute(
        update(AssignmentRubric)
        .where(AssignmentRubric.copied_from_rubric_id == rubric.id)
        .values(copied_from_rubric_id=None)
    )
    db.delete(rubric)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Effective scores
# ---------------------------------------------------------------------------


def _results_by_criterion(db: Session, submission: Submission, criteria: list[RubricCriterion]) -> dict[int, list[CriterionResult]]:
    """Each criterion's results, newest first. When the pinned run has
    results, only that run's count (the pinned run also sets the penalty)."""
    ids = [c.id for c in criteria]
    if not ids:
        return {}
    rows = db.scalars(
        select(CriterionResult)
        .where(CriterionResult.submission_id == submission.id, CriterionResult.criterion_id.in_(ids))
        .order_by(CriterionResult.id.desc())
    ).all()
    if submission.pinned_run_id is not None and any(r.run_id == submission.pinned_run_id for r in rows):
        rows = [r for r in rows if r.run_id == submission.pinned_run_id]
    out: dict[int, list[CriterionResult]] = {}
    for r in rows:
        out.setdefault(r.criterion_id, []).append(r)
    return out


def _clamp(value: float, max_points: float) -> float:
    return max(0.0, min(float(max_points), float(value)))


def submission_breakdown(db: Session, submission: Submission) -> dict[str, Any] | None:
    """The submission's criteria with results, overrides and effective
    scores, or None when its assignment has no rubric.

    A criterion's effective score is its override, else its latest scored
    result, else 0 (counted as 0, shown as not scored). A later attempt that
    failed does not wipe an earlier score; `last_attempt_failed` flags it."""
    rubric = get_rubric(db, submission.assignment_id)
    if rubric is None:
        return None
    criteria = list(rubric.criteria)
    results = _results_by_criterion(db, submission, criteria)
    overrides = {
        o.criterion_id: o
        for o in db.scalars(select(CriterionOverride).where(CriterionOverride.submission_id == submission.id))
    }

    items: list[dict[str, Any]] = []
    total = 0.0
    for c in criteria:
        attempts = results.get(c.id, [])
        scored = next((r for r in attempts if r.status == SCORED and r.score is not None), None)
        latest = attempts[0] if attempts else None
        override = overrides.get(c.id)
        llm_score = _clamp(scored.score, c.max_points) if scored else None
        if override is not None:
            effective = _clamp(override.score, c.max_points)
            source = "override"
        elif llm_score is not None:
            effective = llm_score
            source = "llm"
        else:
            effective = None
            source = None
        total += effective or 0.0
        shown = scored or latest
        items.append(
            {
                **serialize_criterion(c),
                "status": SCORED if scored else NOT_SCORED,
                "llm_score": llm_score,
                "rationale": shown.rationale if shown else "",
                "run_id": shown.run_id if shown else None,
                "model": shown.model if shown else "",
                "error": latest.error if latest is not None and latest.status == NOT_SCORED else "",
                "last_attempt_failed": bool(latest is not None and latest.status == NOT_SCORED and scored is not None),
                "override": (
                    {"score": override.score, "note": override.note, "updated_at": override.updated_at}
                    if override is not None
                    else None
                ),
                "effective_score": effective,
                "source": source,
            }
        )

    max_total = sum(c.max_points for c in criteria)
    return {
        "rubric_id": rubric.id,
        "criteria": items,
        "total": round(total, 4),
        "max_total": round(max_total, 4),
        "percent": round(total / max_total * 100.0, 2) if max_total > 0 else 0.0,
        "not_scored": sum(1 for i in items if i["effective_score"] is None),
    }


def custom_component_score(db: Session, submission: Submission, penalty_multiplier: float) -> float | None:
    """Gradebook component (0-100) from the custom rubric, run-ratio penalty
    applied; None when the assignment has no rubric (use the fixed rubric)."""
    breakdown = submission_breakdown(db, submission)
    if breakdown is None:
        return None
    return round(breakdown["percent"] * penalty_multiplier, 2)


def submission_view(db: Session, submission: Submission) -> dict[str, Any] | None:
    """The breakdown plus the penalty and the resulting gradebook component."""
    from app.services.scoring import _penalty_for_submission

    breakdown = submission_breakdown(db, submission)
    if breakdown is None:
        return None
    penalty = _penalty_for_submission(db, submission)
    return {
        **breakdown,
        "penalty_multiplier": penalty,
        "component_score": round(breakdown["percent"] * penalty, 2),
    }


def set_override(db: Session, submission: Submission, criterion: RubricCriterion, score: float, note: str) -> None:
    row = db.scalar(
        select(CriterionOverride).where(
            CriterionOverride.submission_id == submission.id, CriterionOverride.criterion_id == criterion.id
        )
    )
    if row is None:
        row = CriterionOverride(submission_id=submission.id, criterion_id=criterion.id, score=score, note=note)
        db.add(row)
    row.score = score
    row.note = note
    row.updated_at = datetime.utcnow()
    db.commit()


def clear_override(db: Session, submission: Submission, criterion: RubricCriterion) -> bool:
    row = db.scalar(
        select(CriterionOverride).where(
            CriterionOverride.submission_id == submission.id, CriterionOverride.criterion_id == criterion.id
        )
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Autograder
# ---------------------------------------------------------------------------


def grading_run(db: Session, submission: Submission) -> NotebookRun | None:
    """The pinned run, else the newest run with an executed notebook."""
    if submission.pinned_run_id is not None:
        pinned = db.get(NotebookRun, submission.pinned_run_id)
        if pinned is not None and pinned.executed_notebook_artifact_id is not None:
            return pinned
    return db.scalar(
        select(NotebookRun)
        .where(NotebookRun.submission_id == submission.id, NotebookRun.executed_notebook_artifact_id.is_not(None))
        .order_by(NotebookRun.id.desc())
    )


def deterministic_evidence(submission: Submission, run: NotebookRun | None) -> dict[str, Any]:
    """The fixed pipeline's automatic measurements, for the LLM to weigh."""
    evidence: dict[str, Any] = {}
    try:
        stored = json.loads(submission.code_review_json or "{}")
    except (TypeError, ValueError):
        stored = {}
    for key, payload in (stored.get("dimensions") or {}).items():
        if isinstance(payload, dict) and payload.get("source") == "auto":
            evidence[key] = {"measured_0_to_5": payload.get("score"), "note": payload.get("rationale", "")}
    if run is not None:
        evidence["notebook_execution"] = {
            "cells_ran_ok": run.ok_cells,
            "cells_failed": run.failed_cells,
            "run_ratio": run.run_ratio,
        }
    return evidence


def report_text_for(db: Session, submission: Submission) -> str | None:
    """The written report's text when the submission has one, else None."""
    from app.services import storage
    from app.services.pdf_service import extract_text_from_pdf

    report = db.scalar(
        select(Artifact)
        .where(Artifact.submission_id == submission.id, Artifact.kind == "project_report_pdf")
        .order_by(Artifact.id.desc())
    )
    if report is None:
        return None
    try:
        return extract_text_from_pdf(storage.local_path(report.path))
    except Exception:  # noqa: BLE001
        logger.exception("Could not read report PDF for submission %s", submission.id)
        return ""


def score_submission(db: Session, submission: Submission, run: NotebookRun | None, notebook_path: str) -> dict[str, Any]:
    """Score every criterion of the submission's rubric with the LLM and
    store one result per criterion for `run`. Never raises: when the LLM is
    unavailable or fails, the criteria are stored as not scored. Commits.

    Returns a summary: {"status": "no_rubric" | "scored" | "not_scored", ...}."""
    from app.services.llm_rubric_review import CriterionSpec, notebook_text_with_cells, review_rubric

    rubric = get_rubric(db, submission.assignment_id)
    if rubric is None or not rubric.criteria:
        return {"status": "no_rubric"}
    criteria = list(rubric.criteria)
    specs = [CriterionSpec(c.id, c.name, c.description, c.max_points, criterion_levels(c)) for c in criteria]

    scores: dict[int, tuple[float, str]] = {}
    model = ""
    error = ""
    try:
        result = review_rubric(
            specs,
            notebook_text_with_cells(notebook_path),
            report_text_for(db, submission),
            deterministic_evidence(submission, run),
        )
        scores, model = result.scores, result.model
    except Exception as exc:  # noqa: BLE001  (best-effort: the run must still succeed)
        logger.warning("Custom rubric scoring failed for submission %s: %s", submission.id, exc)
        error = str(exc)[:2000] or exc.__class__.__name__

    run_id = run.id if run is not None else None
    if run_id is not None:
        for old in db.scalars(
            select(CriterionResult).where(CriterionResult.submission_id == submission.id, CriterionResult.run_id == run_id)
        ):
            db.delete(old)
    for c in criteria:
        if c.id in scores:
            score, rationale = scores[c.id]
            db.add(
                CriterionResult(
                    submission_id=submission.id, criterion_id=c.id, run_id=run_id,
                    status=SCORED, score=score, rationale=rationale, model=model,
                )
            )
        else:
            db.add(
                CriterionResult(
                    submission_id=submission.id, criterion_id=c.id, run_id=run_id,
                    status=NOT_SCORED, score=None, rationale="", model=model,
                    error=error or "The model returned no score for this criterion",
                )
            )
    db.commit()
    return {
        "status": SCORED if scores else NOT_SCORED,
        "scored": len(scores),
        "criteria": len(criteria),
        **({"error": error} if error else {}),
    }
