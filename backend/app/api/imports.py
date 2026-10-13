from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import Artifact, Course, Enrollment, PresentationScore, Student
from app.schemas.api import PresentationImportResult
from app.services.presentation_import import aggregate_presentation_rows, parse_presentations_xlsx
from app.services.roster_import import parse_roster_xlsx
from app.services.zip_ingest import ingest_submission_zip
from app.tasks.queue import enqueue
from app.tasks.jobs import parse_originality_pdf

router = APIRouter(prefix="/api/courses/{course_id}/imports", tags=["imports"])


@router.post("/roster")
async def import_roster(course_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    suffix = Path(file.filename or "roster.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        rows = parse_roster_xlsx(tmp_path)
    finally:
        os.unlink(tmp_path)

    imported = 0
    email_conflicts: list[str] = []
    for row in rows:
        student = db.scalar(select(Student).where(Student.national_id == row.national_id))
        if student is None:
            student = Student(national_id=row.national_id, name=row.name)
            db.add(student)
            db.flush()
        else:
            if row.name:
                student.name = row.name
        if row.email and row.email != student.email:
            owner = db.scalar(select(Student).where(Student.email == row.email, Student.id != student.id))
            if owner is None:
                student.email = row.email
            else:
                email_conflicts.append(row.national_id)

        enrollment = db.scalar(
            select(Enrollment).where(Enrollment.course_id == course_id, Enrollment.student_id == student.id)
        )
        if enrollment is None:
            enrollment = Enrollment(course_id=course_id, student_id=student.id)
            db.add(enrollment)
            db.flush()

        if row.attendance_percent is not None:
            enrollment.attendance_percent = row.attendance_percent
        imported += 1

    db.commit()
    return {"imported": imported, "email_conflicts": email_conflicts}


@router.post("/submissions-zip")
async def import_submissions_zip(
    course_id: int,
    file: UploadFile = File(...),
    assignment_type: str = Form(...),
    workcode: int = Form(...),
    assignment_name: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    suffix = Path(file.filename or "submissions.zip").suffix or ".zip"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = ingest_submission_zip(
            db=db,
            course_id=course_id,
            assignment_type=assignment_type.upper(),
            zip_path=tmp_path,
            fallback_workcode=workcode,
            assignment_name=assignment_name,
        )
    finally:
        os.unlink(tmp_path)

    originality_artifacts = db.scalars(
        select(Artifact).where(Artifact.kind == "originality_pdf", Artifact.submission_id.is_not(None)).order_by(Artifact.id.desc()).limit(500)
    ).all()
    for artifact in originality_artifacts:
        enqueue(db, parse_originality_pdf, artifact.id)

    return {
        "created_submissions": result.created_submissions,
        "updated_submissions": result.updated_submissions,
        "created_students": result.created_students,
        "stored_artifacts": result.stored_artifacts,
    }


@router.post("/presentations", response_model=PresentationImportResult)
async def import_presentations(course_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)) -> PresentationImportResult:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    suffix = Path(file.filename or "presentations.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        rows = parse_presentations_xlsx(tmp_path)
        rows = aggregate_presentation_rows(rows)
    finally:
        os.unlink(tmp_path)

    imported_rows = 0
    bonus_updates = 0

    for row in rows:
        student = db.scalar(select(Student).where(Student.national_id == row.national_id))
        if student is None:
            continue

        enrollment = db.scalar(select(Enrollment).where(Enrollment.course_id == course_id, Enrollment.student_id == student.id))
        if enrollment is None:
            enrollment = Enrollment(course_id=course_id, student_id=student.id)
            db.add(enrollment)
            db.flush()

        presentation = db.scalar(
            select(PresentationScore).where(
                PresentationScore.course_id == course_id,
                PresentationScore.student_id == student.id,
                PresentationScore.stage == row.stage,
            )
        )
        if presentation is None:
            presentation = PresentationScore(course_id=course_id, student_id=student.id, stage=row.stage)
            db.add(presentation)

        for field in ["clarity", "complexity", "qa_answers", "elegance", "subjective_impression"]:
            value = getattr(row, field)
            if value is not None:
                setattr(presentation, field, value)

        if row.bonus is not None:
            enrollment.bonus_points += row.bonus
            bonus_updates += 1

        imported_rows += 1

    db.commit()
    return PresentationImportResult(imported_rows=imported_rows, bonus_updates=bonus_updates)
