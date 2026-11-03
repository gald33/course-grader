from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_db
from app.models.entities import (
    Artifact,
    Assignment,
    ColabSnapshot,
    Course,
    CriterionOverride,
    CriterionResult,
    Enrollment,
    NotebookRun,
    RubricDimensionScore,
    Student,
    StudentComponentOverride,
    Submission,
    SubmissionMember,
)
from app.schemas.api import (
    ManualGradeUpdate,
    MissingFlagsUpdate,
    NotesUpdate,
    OverrideCreate,
    RubricApprovalUpdate,
    RubricBulkUpdate,
    RubricDimensionRead,
    SnapshotCreate,
    SnapshotRead,
    SubmissionDetail,
    SubmissionMembersUpdate,
    SubmissionRead,
    SubmissionRequirements,
)
from app.services.consistency import notebook_text_from_ipynb
from app.services.custom_rubrics import submission_view as custom_rubric_view
from app.services.llm_code_review import LLMCodeReviewError, review_code_dimensions
from app.services.llm_review import LLMReviewError, review_project_report
from app.services import storage
from app.services.pdf_service import extract_text_from_pdf
from app.services.scoring import apply_curve, get_active_curve, parse_curve_mapping
from app.tasks.queue import enqueue
from app.tasks.jobs import fetch_colab_snapshot

router = APIRouter(prefix="/api", tags=["submissions"])
logger = logging.getLogger(__name__)


def _compute_requirements(
    db: Session,
    submission_id: int,
    assignment_type: str,
    has_colab_url: bool,
    missing_report_flag: bool = False,
    missing_data_flag: bool = False,
    missing_code_flag: bool = False,
    has_manual_grade: bool = False,
) -> SubmissionRequirements:
    needs_pdf = assignment_type in {"HW1", "PROJECT"}
    needs_colab = assignment_type in {"HW2", "PROJECT"}

    has_pdf = (
        db.scalar(
            select(Artifact.id).where(
                Artifact.submission_id == submission_id,
                Artifact.kind == "project_report_pdf",
            )
        )
        is not None
    )
    if not has_pdf:
        has_pdf = (
            db.scalar(
                select(Artifact.id).where(
                    Artifact.submission_id == submission_id,
                    Artifact.kind == "submission_file",
                    Artifact.filename.ilike("%.pdf"),
                )
            )
            is not None
        )

    has_fetched = (
        db.scalar(
            select(ColabSnapshot.id).where(
                ColabSnapshot.submission_id == submission_id,
                ColabSnapshot.status.in_(("PUBLIC_FETCHED", "PRIVATE_FETCHED")),
            )
        )
        is not None
    )

    missing: list[str] = []
    if needs_pdf and not has_pdf:
        missing.append("PDF")
    if needs_colab and not has_colab_url:
        missing.append("Colab URL")
    if missing_report_flag and "Report" not in missing:
        missing.append("Report")
    if missing_data_flag and "Data" not in missing:
        missing.append("Data")
    if missing_code_flag and "Code" not in missing:
        missing.append("Code")

    # A manual grade short-circuits completeness — the grader has decided this
    # submission is done regardless of what files are or aren't present.
    is_complete = len(missing) == 0 or has_manual_grade

    return SubmissionRequirements(
        needs_pdf=needs_pdf,
        needs_colab=needs_colab,
        has_pdf=has_pdf,
        has_colab_url=has_colab_url,
        has_fetched_colab=has_fetched,
        missing_report_flag=missing_report_flag,
        missing_data_flag=missing_data_flag,
        missing_code_flag=missing_code_flag,
        missing=missing,
        complete=is_complete,
        overridden_by_manual_grade=has_manual_grade,
    )


def _submission_to_read(db: Session, submission: Submission) -> SubmissionRead:
    members = db.scalars(
        select(Student)
        .join(SubmissionMember, SubmissionMember.student_id == Student.id)
        .where(SubmissionMember.submission_id == submission.id)
        .order_by(Student.national_id)
    ).all()

    assignment = db.get(Assignment, submission.assignment_id)

    last_run = db.scalar(
        select(NotebookRun)
        .where(NotebookRun.submission_id == submission.id)
        .order_by(NotebookRun.id.desc())
    )

    has_colab = (
        db.scalar(select(ColabSnapshot.id).where(ColabSnapshot.submission_id == submission.id))
        is not None
    )

    rubric_count = len(
        db.scalars(
            select(RubricDimensionScore).where(RubricDimensionScore.submission_id == submission.id)
        ).all()
    )

    requirements = _compute_requirements(
        db,
        submission.id,
        assignment.assignment_type if assignment else "",
        has_colab,
        missing_report_flag=bool(submission.missing_report_flag),
        missing_data_flag=bool(submission.missing_data_flag),
        missing_code_flag=bool(submission.missing_code_flag),
        has_manual_grade=submission.manual_grade is not None,
    )

    return SubmissionRead(
        id=submission.id,
        course_id=submission.course_id,
        assignment_id=submission.assignment_id,
        assignment_type=assignment.assignment_type if assignment else "",
        workcode=assignment.workcode if assignment else 0,
        group_identifier=submission.group_identifier,
        member_student_ids=[m.id for m in members],
        member_ids=[m.national_id for m in members],
        member_names=[m.name for m in members],
        originality_score_filename=submission.originality_score_filename,
        originality_score_pdf=submission.originality_score_pdf,
        originality_mismatch=submission.originality_mismatch,
        pinned_run_id=submission.pinned_run_id,
        last_run_status=last_run.status if last_run else None,
        last_run_ratio=last_run.run_ratio if last_run else None,
        has_colab_url=has_colab,
        rubric_filled=rubric_count,
        rubric_total=rubric_count,
        requirements=requirements,
        manual_grade=submission.manual_grade,
    )


@router.get("/courses/{course_id}/submissions", response_model=list[SubmissionRead])
def list_submissions(
    course_id: int,
    query: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[SubmissionRead]:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    stmt = (
        select(Submission)
        .where(Submission.course_id == course_id)
        .order_by(Submission.assignment_id.asc(), Submission.id.asc())
    )

    submissions = db.scalars(stmt).all()

    if query:
        q = query.lower().strip()
        filtered = []
        for submission in submissions:
            members = db.scalars(
                select(Student)
                .join(SubmissionMember, SubmissionMember.student_id == Student.id)
                .where(SubmissionMember.submission_id == submission.id)
            ).all()
            haystack = " ".join([submission.group_identifier] + [m.name for m in members] + [m.national_id for m in members]).lower()
            if q in haystack:
                filtered.append(submission)
        submissions = filtered

    return [_submission_to_read(db, item) for item in submissions]


@router.get("/submissions/{submission_id}", response_model=SubmissionDetail)
def get_submission_detail(submission_id: int, db: Session = Depends(get_db)) -> SubmissionDetail:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    snapshots = db.scalars(
        select(ColabSnapshot)
        .where(ColabSnapshot.submission_id == submission_id)
        .order_by(ColabSnapshot.id.desc())
    ).all()

    runs = db.scalars(select(NotebookRun).where(NotebookRun.submission_id == submission_id).order_by(NotebookRun.id.desc())).all()

    rubric_rows = db.scalars(
        select(RubricDimensionScore)
        .where(RubricDimensionScore.submission_id == submission_id)
        .order_by(RubricDimensionScore.component, RubricDimensionScore.dimension_key)
    ).all()

    report_artifact = db.scalar(
        select(Artifact)
        .where(Artifact.submission_id == submission_id, Artifact.kind == "project_report_pdf")
        .order_by(Artifact.id.desc())
    )

    html_artifact_id = None
    pinned = None
    if submission.pinned_run_id:
        pinned = db.get(NotebookRun, submission.pinned_run_id)
    if pinned is None and runs:
        pinned = runs[0]
    if pinned:
        html_artifact_id = pinned.executed_html_artifact_id

    return SubmissionDetail(
        submission=_submission_to_read(db, submission),
        snapshots=[SnapshotRead.model_validate(x) for x in snapshots],
        runs=[
            {
                "id": x.id,
                "submission_id": x.submission_id,
                "snapshot_id": x.snapshot_id,
                "status": x.status,
                "mode": x.mode,
                "ok_cells": x.ok_cells,
                "failed_cells": x.failed_cells,
                "run_ratio": x.run_ratio,
                "penalty_multiplier": x.penalty_multiplier,
                "error_summary": x.error_summary,
                "executed_notebook_artifact_id": x.executed_notebook_artifact_id,
                "executed_html_artifact_id": x.executed_html_artifact_id,
                "log_artifact_id": x.log_artifact_id,
                "is_pinned": x.is_pinned,
                "started_at": x.started_at,
                "ended_at": x.ended_at,
            }
            for x in runs
        ],
        rubric=[
            RubricDimensionRead(
                component=r.component,
                dimension_key=r.dimension_key,
                raw_score=r.raw_score,
                adjusted_score=r.adjusted_score,
                approved=bool(r.approved),
            )
            for r in rubric_rows
        ],
        private_notes=submission.notes_private,
        student_feedback=submission.feedback_student,
        consistency_summary=submission.consistency_summary,
        consistency_flags=json.loads(submission.consistency_flags_json or "[]"),
        report_pdf_artifact_id=report_artifact.id if report_artifact else None,
        executed_html_artifact_id=html_artifact_id,
        artifacts=[
            {
                "id": a.id,
                "kind": a.kind,
                "filename": a.filename,
                "mime_type": a.mime_type,
                "size_bytes": a.size_bytes,
            }
            for a in db.scalars(
                select(Artifact)
                .where(Artifact.submission_id == submission_id)
                .order_by(Artifact.id.asc())
            ).all()
        ],
        llm_review=json.loads(submission.project_llm_review_json)
        if submission.project_llm_review_json
        else None,
        code_review=json.loads(submission.code_review_json)
        if submission.code_review_json
        else None,
        custom_rubric=custom_rubric_view(db, submission),
    )


@router.post("/submissions/{submission_id}/snapshot", response_model=SnapshotRead)
def create_snapshot(submission_id: int, payload: SnapshotCreate, db: Session = Depends(get_db)) -> ColabSnapshot:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    snapshot = ColabSnapshot(submission_id=submission_id, url=str(payload.url), status="PENDING")
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    enqueue(db, fetch_colab_snapshot, snapshot.id)
    db.refresh(snapshot)
    return snapshot


@router.delete("/submissions/{submission_id}/snapshots")
def delete_all_snapshots(submission_id: int, db: Session = Depends(get_db)) -> dict:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    snapshots = db.scalars(
        select(ColabSnapshot).where(ColabSnapshot.submission_id == submission_id)
    ).all()
    for snap in snapshots:
        db.delete(snap)
    db.commit()
    return {"status": "ok", "deleted": len(snapshots)}


@router.delete("/submissions/{submission_id}")
def delete_submission(submission_id: int, db: Session = Depends(get_db)) -> dict:
    """Delete a submission, every row hanging off it, and its stored files.

    Rows go explicitly in dependency order rather than through ORM cascades:
    runs point at both snapshots and artifacts, and the submission points back
    at its pinned run, so the order matters on Postgres."""
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    locations = set(db.scalars(select(Artifact.path).where(Artifact.submission_id == submission_id)).all())

    db.execute(update(Submission).where(Submission.id == submission_id).values(pinned_run_id=None))
    for model in (
        CriterionResult,
        CriterionOverride,
        NotebookRun,
        ColabSnapshot,
        Artifact,
        RubricDimensionScore,
        StudentComponentOverride,
        SubmissionMember,
    ):
        db.execute(delete(model).where(model.submission_id == submission_id))
    db.execute(delete(Submission).where(Submission.id == submission_id))
    db.commit()

    # Files go after the commit: a failed storage call leaves an orphaned
    # object, never a row pointing at a missing file. Skip any location
    # another artifact row still uses.
    if locations:
        locations -= set(db.scalars(select(Artifact.path).where(Artifact.path.in_(locations))).all())
    removed = 0
    for location in locations:
        try:
            storage.delete(location)
            removed += 1
        except Exception:  # noqa: BLE001
            logger.exception("Could not delete stored file %s of submission %s", location, submission_id)
    return {"status": "ok", "files_deleted": removed, "files_failed": len(locations) - removed}


@router.put("/submissions/{submission_id}/members", response_model=SubmissionRead)
def set_submission_members(
    submission_id: int, payload: SubmissionMembersUpdate, db: Session = Depends(get_db)
) -> SubmissionRead:
    """Replace the group behind a submission. Scores follow membership, so a
    removed student stops getting this submission's grade; their overrides
    tied to this submission go too."""
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    wanted = set(payload.student_ids)
    enrolled = set(
        db.scalars(
            select(Enrollment.student_id).where(
                Enrollment.course_id == submission.course_id, Enrollment.student_id.in_(wanted)
            )
        ).all()
    )
    if wanted - enrolled:
        raise HTTPException(
            status_code=400,
            detail=f"Not enrolled in this course: student ids {sorted(wanted - enrolled)}",
        )

    current = set(
        db.scalars(select(SubmissionMember.student_id).where(SubmissionMember.submission_id == submission_id)).all()
    )
    removed = current - wanted
    if removed:
        db.execute(
            delete(SubmissionMember).where(
                SubmissionMember.submission_id == submission_id, SubmissionMember.student_id.in_(removed)
            )
        )
        db.execute(
            delete(StudentComponentOverride).where(
                StudentComponentOverride.submission_id == submission_id,
                StudentComponentOverride.student_id.in_(removed),
            )
        )
    for student_id in sorted(wanted - current):
        db.add(SubmissionMember(submission_id=submission_id, student_id=student_id))
    db.commit()
    db.refresh(submission)
    return _submission_to_read(db, submission)


@router.put("/submissions/{submission_id}/rubric")
def upsert_rubric(submission_id: int, payload: RubricBulkUpdate, db: Session = Depends(get_db)) -> dict:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    curve = parse_curve_mapping(get_active_curve(db, submission.course_id))

    for dim in payload.dimensions:
        row = db.scalar(
            select(RubricDimensionScore).where(
                RubricDimensionScore.submission_id == submission_id,
                RubricDimensionScore.component == dim.component,
                RubricDimensionScore.dimension_key == dim.dimension_key,
            )
        )
        points = curve.get(dim.dimension_key, {"points": [0, 1, 2, 3, 4, 5]})["points"]
        adjusted = apply_curve(dim.raw_score, points)
        if row is None:
            row = RubricDimensionScore(
                submission_id=submission_id,
                component=dim.component,
                dimension_key=dim.dimension_key,
                raw_score=dim.raw_score,
                adjusted_score=adjusted,
                approved=dim.approved,
            )
            db.add(row)
        else:
            row.raw_score = dim.raw_score
            row.adjusted_score = adjusted
            row.approved = dim.approved

    db.commit()
    return {"status": "ok", "count": len(payload.dimensions)}


@router.post("/submissions/{submission_id}/rubric/approve")
def set_rubric_approval(
    submission_id: int, payload: RubricApprovalUpdate, db: Session = Depends(get_db)
) -> dict:
    """Toggle the approved flag on a single dimension without changing its score.

    Used by the inline ✓ button — the grader confirms an LLM-suggested score
    without nudging the dot.
    """
    row = db.scalar(
        select(RubricDimensionScore).where(
            RubricDimensionScore.submission_id == submission_id,
            RubricDimensionScore.component == payload.component,
            RubricDimensionScore.dimension_key == payload.dimension_key,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Dimension not yet scored")
    row.approved = payload.approved
    db.commit()
    return {"status": "ok", "approved": row.approved}


@router.post("/submissions/{submission_id}/llm-review/apply")
def apply_llm_review(submission_id: int, db: Session = Depends(get_db)) -> dict:
    """Write the stored LLM-suggested scores into the rubric as `approved=False`.

    Idempotent: existing manually-approved scores are left alone (we never
    overwrite a grader's decision); rows that don't exist yet get created with
    the LLM's score and `approved=False`; previously-LLM-applied rows that the
    grader hasn't approved get refreshed if the LLM has since re-suggested.
    """
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    if not submission.project_llm_review_json:
        raise HTTPException(status_code=400, detail="No stored LLM review for this submission")

    review = json.loads(submission.project_llm_review_json)
    dims = review.get("dimensions", {})
    if not isinstance(dims, dict) or not dims:
        raise HTTPException(status_code=400, detail="Stored LLM review is empty")

    curve = parse_curve_mapping(get_active_curve(db, submission.course_id))
    component = "project_report"
    written = 0
    skipped_approved = 0

    for dim_key, payload in dims.items():
        if not isinstance(payload, dict):
            continue
        score = payload.get("score")
        if not isinstance(score, (int, float)):
            continue
        score = max(0.0, min(5.0, float(score)))

        existing = db.scalar(
            select(RubricDimensionScore).where(
                RubricDimensionScore.submission_id == submission_id,
                RubricDimensionScore.component == component,
                RubricDimensionScore.dimension_key == dim_key,
            )
        )
        if existing is not None and existing.approved:
            # Don't clobber a grader's decision.
            skipped_approved += 1
            continue

        points = curve.get(dim_key, {"points": [0, 1, 2, 3, 4, 5]})["points"]
        adjusted = apply_curve(score, points)
        if existing is None:
            db.add(
                RubricDimensionScore(
                    submission_id=submission_id,
                    component=component,
                    dimension_key=dim_key,
                    raw_score=score,
                    adjusted_score=adjusted,
                    approved=False,
                )
            )
        else:
            existing.raw_score = score
            existing.adjusted_score = adjusted
            existing.approved = False
        written += 1

    db.commit()
    return {"status": "ok", "written": written, "skipped_approved": skipped_approved}


_LLM_CODE_DIMS: set[str] = {"processing_description", "models_quality"}
_LLM_REPORT_DIMS = {
    "research_question_hypothesis",
    "data_description",
    "data_processing",
    "models_comparison",
    "results_analysis",
    "consistency_with_code",
}
_LLM_DIMS_BY_COMPONENT = {
    "project_code": _LLM_CODE_DIMS,
    "hw2_code": _LLM_CODE_DIMS,
    "project_report": _LLM_REPORT_DIMS,
}


@router.post("/submissions/{submission_id}/rubric/{component}/{dimension_key}/rescore-llm")
def rescore_one_llm_dim(
    submission_id: int,
    component: str,
    dimension_key: str,
    db: Session = Depends(get_db),
) -> dict:
    """Re-run the LLM scorer for ONE rubric dimension and overwrite that single
    score (approved=False so the grader reviews). Other dims are untouched even
    though the underlying LLM call may score them too — we discard the rest."""
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    valid = _LLM_DIMS_BY_COMPONENT.get(component)
    if not valid or dimension_key not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"{component}/{dimension_key} is not an LLM-scored dimension",
        )

    nb_path = _find_pinned_executed_notebook(db, submission)
    if nb_path is None:
        raise HTTPException(
            status_code=400,
            detail="No executed notebook for this submission — run it first",
        )
    try:
        nb_text = notebook_text_from_ipynb(nb_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to read notebook: {exc}") from exc

    if component in {"project_code", "hw2_code"}:
        try:
            result = review_code_dimensions(nb_text)
        except LLMCodeReviewError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("code-review LLM failed for sub %s", submission_id)
            raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc
        scored = result.scores.get(dimension_key)
        json_field = "code_review_json"
    else:
        report_artifact = db.scalar(
            select(Artifact)
            .where(
                Artifact.submission_id == submission_id,
                Artifact.kind == "project_report_pdf",
            )
            .order_by(Artifact.id.desc())
        )
        if report_artifact is None:
            report_artifact = db.scalar(
                select(Artifact)
                .where(
                    Artifact.submission_id == submission_id,
                    Artifact.kind == "submission_file",
                    Artifact.filename.ilike("%.pdf"),
                )
                .order_by(Artifact.id.desc())
            )
        if report_artifact is None:
            raise HTTPException(status_code=400, detail="No report PDF on this submission")
        try:
            pdf_text = extract_text_from_pdf(storage.local_path(report_artifact.path))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Failed to read PDF: {exc}") from exc
        if not pdf_text or not pdf_text.strip():
            raise HTTPException(status_code=400, detail="Report PDF text extraction returned empty")
        try:
            result = review_project_report(pdf_text, nb_text)
        except LLMReviewError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("report-review LLM failed for sub %s", submission_id)
            raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc
        scored = result.dimensions.get(dimension_key)
        json_field = "project_llm_review_json"

    if not isinstance(scored, dict) or "score" not in scored:
        raise HTTPException(status_code=502, detail=f"LLM did not return a score for {dimension_key}")
    score = max(0.0, min(5.0, float(scored["score"])))
    rationale = str(scored.get("rationale", ""))

    curve = parse_curve_mapping(get_active_curve(db, submission.course_id))
    points = curve.get(dimension_key, {"points": [0, 1, 2, 3, 4, 5]})["points"]
    adjusted = apply_curve(score, points)

    row = db.scalar(
        select(RubricDimensionScore).where(
            RubricDimensionScore.submission_id == submission_id,
            RubricDimensionScore.component == component,
            RubricDimensionScore.dimension_key == dimension_key,
        )
    )
    if row is None:
        db.add(
            RubricDimensionScore(
                submission_id=submission_id,
                component=component,
                dimension_key=dimension_key,
                raw_score=score,
                adjusted_score=adjusted,
                approved=False,
            )
        )
    else:
        row.raw_score = score
        row.adjusted_score = adjusted
        row.approved = False

    existing_str = getattr(submission, json_field) or ""
    try:
        blob = json.loads(existing_str) if existing_str else {}
    except json.JSONDecodeError:
        blob = {}
    if not isinstance(blob, dict):
        blob = {}
    if json_field == "code_review_json":
        blob.setdefault("component", component)
        dims = blob.setdefault("dimensions", {})
        if not isinstance(dims, dict):
            dims = {}
            blob["dimensions"] = dims
        dims[dimension_key] = {"score": score, "rationale": rationale, "source": "claude"}
    else:
        dims = blob.setdefault("dimensions", {})
        if not isinstance(dims, dict):
            dims = {}
            blob["dimensions"] = dims
        dims[dimension_key] = {"score": score, "rationale": rationale}
    setattr(submission, json_field, json.dumps(blob, ensure_ascii=False))

    db.commit()
    return {
        "status": "ok",
        "component": component,
        "dimension_key": dimension_key,
        "score": score,
        "adjusted_score": adjusted,
        "rationale": rationale,
        "source": "claude",
    }


@router.patch("/submissions/{submission_id}/notes")
def update_notes(submission_id: int, payload: NotesUpdate, db: Session = Depends(get_db)) -> dict:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    submission.notes_private = payload.notes_private
    submission.feedback_student = payload.feedback_student
    db.commit()
    return {"status": "ok"}


def _find_pinned_executed_notebook(db: Session, submission: Submission) -> str | None:
    """Resolve the executed notebook artifact path for the pinned/most-recent run."""
    pinned = None
    if submission.pinned_run_id:
        pinned = db.get(NotebookRun, submission.pinned_run_id)
    if pinned is None:
        pinned = db.scalar(
            select(NotebookRun)
            .where(NotebookRun.submission_id == submission.id)
            .order_by(NotebookRun.id.desc())
        )
    if pinned is None or pinned.executed_notebook_artifact_id is None:
        return None
    art = db.get(Artifact, pinned.executed_notebook_artifact_id)
    return str(storage.local_path(art.path)) if art else None


@router.post("/submissions/{submission_id}/llm-review")
def run_llm_review(submission_id: int, db: Session = Depends(get_db)) -> dict:
    """Ask Claude Sonnet 4.6 to suggest project_report rubric scores + a Hebrew
    feedback paragraph. Persists the result as JSON on the submission so the
    grader can revisit it without re-running.
    """
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    assignment = db.get(Assignment, submission.assignment_id)
    if not assignment or assignment.assignment_type != "PROJECT":
        raise HTTPException(
            status_code=400, detail="LLM review only supports PROJECT submissions"
        )

    # Report PDF — required.
    report_artifact = db.scalar(
        select(Artifact)
        .where(
            Artifact.submission_id == submission_id,
            Artifact.kind == "project_report_pdf",
        )
        .order_by(Artifact.id.desc())
    )
    if report_artifact is None:
        # Fall back to any submission_file PDF.
        report_artifact = db.scalar(
            select(Artifact)
            .where(
                Artifact.submission_id == submission_id,
                Artifact.kind == "submission_file",
                Artifact.filename.ilike("%.pdf"),
            )
            .order_by(Artifact.id.desc())
        )
    if report_artifact is None:
        raise HTTPException(status_code=400, detail="No report PDF on this submission")

    try:
        pdf_text = extract_text_from_pdf(storage.local_path(report_artifact.path))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Failed to read report PDF: {exc}"
        ) from exc

    if not pdf_text or not pdf_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Report PDF text extraction returned empty — cannot run LLM review",
        )

    # Executed notebook — optional but strongly recommended for the
    # consistency_with_code dimension.
    notebook_text = ""
    nb_path = _find_pinned_executed_notebook(db, submission)
    if nb_path:
        try:
            notebook_text = notebook_text_from_ipynb(nb_path)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to read executed notebook for sub %s", submission_id)

    try:
        result = review_project_report(pdf_text, notebook_text)
    except LLMReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM review failed for sub %s", submission_id)
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc

    payload = {
        "model": result.model,
        "dimensions": result.dimensions,
        "feedback_he": result.feedback_he,
        "usage": result.usage,
    }
    submission.project_llm_review_json = json.dumps(payload, ensure_ascii=False)
    db.commit()
    return payload


@router.patch("/submissions/{submission_id}/manual-grade")
def update_manual_grade(
    submission_id: int, payload: ManualGradeUpdate, db: Session = Depends(get_db)
) -> dict:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    if payload.manual_grade is not None:
        if payload.manual_grade < 0 or payload.manual_grade > 100:
            raise HTTPException(status_code=400, detail="manual_grade must be between 0 and 100")
    submission.manual_grade = payload.manual_grade
    db.commit()
    return {"status": "ok", "manual_grade": submission.manual_grade}


@router.patch("/submissions/{submission_id}/flags")
def update_missing_flags(
    submission_id: int, payload: MissingFlagsUpdate, db: Session = Depends(get_db)
) -> dict:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    if payload.missing_report_flag is not None:
        submission.missing_report_flag = payload.missing_report_flag
    if payload.missing_data_flag is not None:
        submission.missing_data_flag = payload.missing_data_flag
    if payload.missing_code_flag is not None:
        submission.missing_code_flag = payload.missing_code_flag
    db.commit()
    return {
        "status": "ok",
        "missing_report_flag": bool(submission.missing_report_flag),
        "missing_data_flag": bool(submission.missing_data_flag),
        "missing_code_flag": bool(submission.missing_code_flag),
    }


@router.post("/courses/{course_id}/overrides")
def create_override(course_id: int, payload: OverrideCreate, db: Session = Depends(get_db)) -> dict:
    if not payload.reason.strip():
        raise HTTPException(status_code=400, detail="Reason is required")

    override = StudentComponentOverride(
        course_id=course_id,
        student_id=payload.student_id,
        submission_id=payload.submission_id,
        component=payload.component,
        delta=payload.delta,
        reason=payload.reason,
    )
    db.add(override)
    db.commit()
    db.refresh(override)
    return {"status": "ok", "override_id": override.id}


@router.get("/courses/{course_id}/overrides")
def list_overrides(course_id: int, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(
        select(StudentComponentOverride)
        .where(StudentComponentOverride.course_id == course_id)
        .order_by(StudentComponentOverride.created_at.desc())
    ).all()
    students = {s.id: s for s in db.scalars(select(Student)).all()}
    return [
        {
            "id": o.id,
            "student_id": o.student_id,
            "student_name": students[o.student_id].name if o.student_id in students else None,
            "student_national_id": students[o.student_id].national_id if o.student_id in students else None,
            "submission_id": o.submission_id,
            "component": o.component,
            "delta": o.delta,
            "reason": o.reason,
            "created_at": o.created_at,
        }
        for o in rows
    ]


@router.delete("/courses/{course_id}/overrides/{override_id}")
def delete_override(course_id: int, override_id: int, db: Session = Depends(get_db)) -> dict:
    override = db.get(StudentComponentOverride, override_id)
    if not override or override.course_id != course_id:
        raise HTTPException(status_code=404, detail="Override not found")
    db.delete(override)
    db.commit()
    return {"status": "ok"}
