from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_db
from app.models.entities import (
    Artifact,
    Assignment,
    ColabSnapshot,
    Course,
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
    RubricBulkUpdate,
    RubricDimensionRead,
    SnapshotCreate,
    SnapshotRead,
    SubmissionDetail,
    SubmissionRead,
    SubmissionRequirements,
)
from app.services.scoring import apply_curve, get_active_curve, parse_curve_mapping
from app.tasks.dispatch import safe_delay
from app.tasks.jobs import fetch_colab_snapshot

router = APIRouter(prefix="/api", tags=["submissions"])


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

    enqueued_task_id = safe_delay(fetch_colab_snapshot, snapshot.id)
    if enqueued_task_id is None:
        snapshot.status = "FAILED"
        snapshot.error_message = "Queue unavailable. Check Redis/worker."
        db.commit()
        db.refresh(snapshot)
    return snapshot


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
            )
            db.add(row)
        else:
            row.raw_score = dim.raw_score
            row.adjusted_score = adjusted

    db.commit()
    return {"status": "ok", "count": len(payload.dimensions)}


@router.patch("/submissions/{submission_id}/notes")
def update_notes(submission_id: int, payload: NotesUpdate, db: Session = Depends(get_db)) -> dict:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    submission.notes_private = payload.notes_private
    submission.feedback_student = payload.feedback_student
    db.commit()
    return {"status": "ok"}


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
