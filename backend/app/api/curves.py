from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import CurveRevision, Submission
from app.schemas.api import CurveRevisionIn, CurveRevisionRead
from app.services.scoring import (
    calibrate_curves_to_mean,
    get_active_curve,
    parse_curve_mapping,
    recalculate_submission_adjusted_scores,
    save_curve_revision,
)

router = APIRouter(prefix="/api/courses/{course_id}/curves", tags=["curves"])


@router.get("/active", response_model=CurveRevisionRead)
def get_active(course_id: int, db: Session = Depends(get_db)) -> CurveRevisionRead:
    active = get_active_curve(db, course_id)
    mapping = parse_curve_mapping(active)
    return CurveRevisionRead(
        id=active.id,
        revision_number=active.revision_number,
        note=active.note,
        mapping=mapping,
        created_at=active.created_at,
    )


@router.post("/revision", response_model=CurveRevisionRead)
def create_revision(course_id: int, payload: CurveRevisionIn, db: Session = Depends(get_db)) -> CurveRevisionRead:
    mapping = {k: {"points": v.points, "tunable": v.tunable} for k, v in payload.mapping.items()}
    rev = save_curve_revision(db, course_id, mapping, payload.note)

    submissions = db.scalars(select(Submission.id).where(Submission.course_id == course_id)).all()
    for submission_id in submissions:
        recalculate_submission_adjusted_scores(db, course_id, submission_id)

    return CurveRevisionRead(
        id=rev.id,
        revision_number=rev.revision_number,
        note=rev.note,
        mapping=parse_curve_mapping(rev),
        created_at=rev.created_at,
    )


@router.post("/calibrate-mean-83", response_model=CurveRevisionRead)
def calibrate(course_id: int, db: Session = Depends(get_db)) -> CurveRevisionRead:
    rev = calibrate_curves_to_mean(db, course_id, target_mean=83.0)
    return CurveRevisionRead(
        id=rev.id,
        revision_number=rev.revision_number,
        note=rev.note,
        mapping=parse_curve_mapping(rev),
        created_at=rev.created_at,
    )


@router.post("/undo", response_model=CurveRevisionRead)
def undo(course_id: int, db: Session = Depends(get_db)) -> CurveRevisionRead:
    revisions = db.scalars(
        select(CurveRevision).where(CurveRevision.course_id == course_id).order_by(desc(CurveRevision.revision_number))
    ).all()
    if len(revisions) < 2:
        raise HTTPException(status_code=400, detail="No previous revision to restore")

    current = revisions[0]
    previous = revisions[1]
    current.is_active = False
    previous.is_active = True
    db.commit()

    submissions = db.scalars(select(Submission.id).where(Submission.course_id == course_id)).all()
    for submission_id in submissions:
        recalculate_submission_adjusted_scores(db, course_id, submission_id)

    db.refresh(previous)
    return CurveRevisionRead(
        id=previous.id,
        revision_number=previous.revision_number,
        note=previous.note,
        mapping=parse_curve_mapping(previous),
        created_at=previous.created_at,
    )
