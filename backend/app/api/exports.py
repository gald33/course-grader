from __future__ import annotations

from celery.result import AsyncResult
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.exporter import export_student_reports_hebrew
from app.tasks.celery_app import celery_app
from app.tasks.dispatch import safe_delay
from app.tasks.jobs import export_student_reports

router = APIRouter(prefix="/api", tags=["exports"])


@router.post("/courses/{course_id}/exports/student-reports")
def queue_student_reports_export(course_id: int, async_job: bool = True, db: Session = Depends(get_db)) -> dict:
    if async_job:
        task_id = safe_delay(export_student_reports, course_id)
        if task_id is None:
            return {"status": "queue_unavailable", "detail": "Redis/worker is not reachable"}
        return {"status": "queued", "task_id": task_id}

    result = export_student_reports_hebrew(db, course_id)
    return {
        "status": "ok",
        "csv_path": result.csv_path,
        "report_dir": result.report_dir,
        "report_count": result.report_count,
    }


@router.get("/tasks/{task_id}")
def task_status(task_id: str) -> dict:
    result = AsyncResult(task_id, app=celery_app)
    payload = result.result if isinstance(result.result, dict) else {"result": str(result.result)}
    return {"task_id": task_id, "state": result.state, "payload": payload}
