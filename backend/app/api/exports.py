from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import Job
from app.services.exporter import export_student_reports_hebrew
from app.tasks.jobs import export_student_reports
from app.tasks.queue import enqueue

router = APIRouter(prefix="/api", tags=["exports"])

# Job status in the state names the Celery-based API used.
_STATES = {"queued": "PENDING", "running": "STARTED", "succeeded": "SUCCESS", "failed": "FAILURE"}


@router.post("/courses/{course_id}/exports/student-reports")
def queue_student_reports_export(course_id: int, async_job: bool = True, db: Session = Depends(get_db)) -> dict:
    if async_job:
        return {"status": "queued", "task_id": enqueue(db, export_student_reports, course_id)}

    result = export_student_reports_hebrew(db, course_id)
    return {
        "status": "ok",
        "csv_path": result.csv_path,
        "report_dir": result.report_dir,
        "report_count": result.report_count,
    }


@router.get("/tasks/{task_id}")
def task_status(task_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Job, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if row.status == "failed":
        payload = {"error": row.error.strip().splitlines()[-1] if row.error.strip() else "failed"}
    else:
        result = json.loads(row.result_json) if row.result_json else None
        payload = result if isinstance(result, dict) else {"result": result}
    return {"task_id": str(row.id), "state": _STATES.get(row.status, row.status.upper()), "payload": payload}
