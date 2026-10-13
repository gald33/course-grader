from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import ColabSnapshot, NotebookRun, Submission
from app.schemas.api import RunCreate, RunRead
from app.tasks.queue import enqueue
from app.tasks.jobs import fetch_and_run_latest, run_notebook

router = APIRouter(prefix="/api", tags=["runs"])


@router.get("/submissions/{submission_id}/runs", response_model=list[RunRead])
def list_runs(submission_id: int, db: Session = Depends(get_db)) -> list[NotebookRun]:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    return db.scalars(select(NotebookRun).where(NotebookRun.submission_id == submission_id).order_by(NotebookRun.id.desc())).all()


@router.post("/submissions/{submission_id}/runs", response_model=RunRead)
def create_run(submission_id: int, payload: RunCreate, db: Session = Depends(get_db)) -> NotebookRun:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    if payload.mode == "snapshot":
        snapshot_id = payload.snapshot_id
        if snapshot_id is None:
            latest = db.scalar(
                select(ColabSnapshot)
                .where(
                    ColabSnapshot.submission_id == submission_id,
                    ColabSnapshot.status.in_(["PUBLIC_FETCHED", "PRIVATE_FETCHED"]),
                )
                .order_by(ColabSnapshot.id.desc())
            )
            if latest is None:
                raise HTTPException(status_code=400, detail="No fetched snapshot available")
            snapshot_id = latest.id

        run = NotebookRun(submission_id=submission_id, snapshot_id=snapshot_id, mode="snapshot", status="QUEUED")
        db.add(run)
        db.commit()
        db.refresh(run)
        enqueue(db, run_notebook, run.id)
        return run

    latest_snapshot = db.scalar(select(ColabSnapshot).where(ColabSnapshot.submission_id == submission_id).order_by(ColabSnapshot.id.desc()))
    if latest_snapshot is None:
        raise HTTPException(status_code=400, detail="No previous snapshot URL available")

    new_snapshot = ColabSnapshot(submission_id=submission_id, url=latest_snapshot.url, status="PENDING")
    db.add(new_snapshot)
    db.commit()
    db.refresh(new_snapshot)

    run = NotebookRun(submission_id=submission_id, snapshot_id=new_snapshot.id, mode="latest", status="QUEUED")
    db.add(run)
    db.commit()
    db.refresh(run)

    enqueue(db, fetch_and_run_latest, submission_id, new_snapshot.id)
    return run


@router.post("/runs/{run_id}/pin")
def pin_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    run = db.get(NotebookRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    submission = db.get(Submission, run.submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    all_runs = db.scalars(select(NotebookRun).where(NotebookRun.submission_id == submission.id)).all()
    for item in all_runs:
        item.is_pinned = item.id == run_id

    submission.pinned_run_id = run_id
    db.commit()
    return {"status": "ok"}
