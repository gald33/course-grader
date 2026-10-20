from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import Course, Job
from app.services import storage
from app.services.exporter import export_student_reports_hebrew
from app.tasks.jobs import export_student_reports
from app.tasks.queue import enqueue
from app.utils.text import sanitize_filename

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
        "zip_location": result.zip_location,
        "report_count": result.report_count,
    }


@router.get("/courses/{course_id}/exports/student-reports/{task_id}/download")
def download_student_reports(course_id: int, task_id: int, db: Session = Depends(get_db)) -> Response:
    """The zip of PDFs a finished export job stored. On Supabase storage this
    redirects to a short-lived signed URL, so it works on the hosted site."""
    row = db.get(Job, task_id)
    if (
        row is None
        or row.name != export_student_reports.job_name
        or json.loads(row.args_json or "[]") != [course_id]
    ):
        raise HTTPException(status_code=404, detail="Export not found")
    if row.status != "succeeded":
        raise HTTPException(status_code=409, detail=f"Export is {row.status}")
    location = (json.loads(row.result_json or "{}") or {}).get("zip_location")
    if not location:
        raise HTTPException(status_code=404, detail="Export has no stored reports")

    course = db.get(Course, course_id)
    suffix = f"_{course.code}_{course.year}_{course.semester}" if course else ""
    name = sanitize_filename(f"student_reports{suffix}") + ".zip"
    if storage.is_remote(location):
        return RedirectResponse(storage.signed_url(location, download_name=name), status_code=307)
    if not Path(location).exists():
        raise HTTPException(status_code=404, detail="Export file missing")
    return FileResponse(location, media_type="application/zip", filename=name)


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
