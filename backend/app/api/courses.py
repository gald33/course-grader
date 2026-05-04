from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import Course, Enrollment
from app.schemas.api import (
    AttendanceExemptUpdate,
    AttendanceThresholdUpdate,
    BonusUpdate,
    CourseCreate,
    CourseRead,
)

router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.get("", response_model=list[CourseRead])
def list_courses(db: Session = Depends(get_db)) -> list[Course]:
    return db.scalars(select(Course).order_by(Course.year.desc(), Course.semester, Course.code)).all()


@router.post("", response_model=CourseRead)
def create_course(payload: CourseCreate, db: Session = Depends(get_db)) -> Course:
    course = Course(
        code=payload.code,
        name=payload.name,
        year=payload.year,
        semester=payload.semester,
        attendance_threshold=payload.attendance_threshold,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@router.get("/{course_id}", response_model=CourseRead)
def get_course(course_id: int, db: Session = Depends(get_db)) -> Course:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@router.patch("/{course_id}/attendance-threshold", response_model=CourseRead)
def update_threshold(course_id: int, payload: AttendanceThresholdUpdate, db: Session = Depends(get_db)) -> Course:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    course.attendance_threshold = payload.threshold
    db.commit()
    db.refresh(course)
    return course


@router.post("/{course_id}/attendance/threshold-for-25-fail", response_model=CourseRead)
def set_threshold_25_fail(course_id: int, db: Session = Depends(get_db)) -> Course:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    values = [
        float(x)
        for x in db.scalars(
            select(Enrollment.attendance_percent).where(
                Enrollment.course_id == course_id,
                Enrollment.attendance_percent.is_not(None),
                Enrollment.attendance_exempt.is_(False),
            )
        ).all()
    ]
    if not values:
        raise HTTPException(status_code=400, detail="No attendance data available")

    values.sort()
    keep_count = max(1, int(round(len(values) * 0.75)))
    threshold = values[len(values) - keep_count]
    course.attendance_threshold = threshold
    db.commit()
    db.refresh(course)
    return course


@router.patch("/{course_id}/enrollments/{enrollment_id}/attendance-exempt")
def set_attendance_exempt(
    course_id: int,
    enrollment_id: int,
    payload: AttendanceExemptUpdate,
    db: Session = Depends(get_db),
) -> dict:
    enrollment = db.get(Enrollment, enrollment_id)
    if not enrollment or enrollment.course_id != course_id:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    enrollment.attendance_exempt = payload.attendance_exempt
    db.commit()
    return {"status": "ok"}


@router.patch("/{course_id}/enrollments/{enrollment_id}/bonus")
def set_bonus(
    course_id: int,
    enrollment_id: int,
    payload: BonusUpdate,
    db: Session = Depends(get_db),
) -> dict:
    enrollment = db.get(Enrollment, enrollment_id)
    if not enrollment or enrollment.course_id != course_id:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    enrollment.bonus_points = payload.bonus_points
    db.commit()
    return {"status": "ok"}
