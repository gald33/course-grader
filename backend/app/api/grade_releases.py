"""Instructor controls for which gradebook components students can see."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.peer_review import iso
from app.models.entities import Course
from app.services import student_grades

router = APIRouter(prefix="/api/courses/{course_id}/grade-releases", tags=["gradebook"])


class ReleaseIn(BaseModel):
    released: bool


def _state(db: Session, course_id: int) -> dict:
    released = student_grades.released_components(db, course_id)
    return {
        "components": [
            {
                "key": key,
                "released": key in released,
                "released_at": iso(released[key].released_at) if key in released else None,
            }
            for key in student_grades.COMPONENTS
        ]
    }


@router.get("")
def get_releases(course_id: int, db: Session = Depends(get_db)) -> dict:
    if db.get(Course, course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return _state(db, course_id)


@router.put("/{component}")
def set_release(course_id: int, component: str, payload: ReleaseIn, db: Session = Depends(get_db)) -> dict:
    if db.get(Course, course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")
    if component not in student_grades.COMPONENTS:
        raise HTTPException(status_code=404, detail="Unknown grade component")
    student_grades.set_released(db, course_id, component, payload.released)
    return _state(db, course_id)
