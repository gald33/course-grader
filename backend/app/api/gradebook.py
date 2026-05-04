from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.api import GradebookResponse
from app.services.exporter import export_gradebook_csv
from app.services.scoring import compute_gradebook_rows

router = APIRouter(prefix="/api/courses/{course_id}/gradebook", tags=["gradebook"])


@router.get("", response_model=GradebookResponse)
def get_gradebook(course_id: int, db: Session = Depends(get_db)) -> GradebookResponse:
    rows = compute_gradebook_rows(db, course_id)
    return GradebookResponse(rows=rows)


@router.get("/csv")
def get_gradebook_csv(course_id: int, db: Session = Depends(get_db)) -> FileResponse:
    csv_path = export_gradebook_csv(db, course_id)
    return FileResponse(csv_path, media_type="text/csv", filename="gradebook.csv")
