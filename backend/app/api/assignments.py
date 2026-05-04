from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import Assignment, Course

router = APIRouter(prefix="/api/courses/{course_id}/assignments", tags=["assignments"])


@router.get("")
def list_assignments(course_id: int, db: Session = Depends(get_db)) -> list[dict]:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    assignments = db.scalars(
        select(Assignment).where(Assignment.course_id == course_id).order_by(Assignment.assignment_type, Assignment.workcode)
    ).all()
    return [
        {
            "id": a.id,
            "workcode": a.workcode,
            "name": a.name,
            "assignment_type": a.assignment_type,
            "submission_count": len(a.submissions),
        }
        for a in assignments
    ]
