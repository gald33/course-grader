from __future__ import annotations

import os
import tempfile
from pathlib import Path

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import Artifact, Course, Enrollment, PresentationScore, Student, StudentComponentOverride
from app.schemas.api import PresentationImportResult
from app.services.presentation_import import aggregate_presentation_rows, parse_presentations_xlsx
from app.services import storage
from app.services.roster_import import parse_roster_xlsx
from app.services.zip_ingest import ingest_submission_zip
from app.utils.text import sanitize_filename
from app.tasks.queue import enqueue
from app.tasks.jobs import parse_originality_pdf

router = APIRouter(prefix="/api/courses/{course_id}/imports", tags=["imports"])


class ImportUploadIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)


def _upload_prefix(course_id: int) -> str:
    return f"imports/{course_id}/"


@router.post("/upload-url")
def import_upload_url(course_id: int, payload: ImportUploadIn) -> dict:
    """Signed URL for sending an import file straight to Storage (hosted
    request bodies are capped). Pass the returned key as `storage_key`."""
    if not storage.direct_uploads_enabled():
        return {"direct": False}
    key = f"{_upload_prefix(course_id)}{uuid.uuid4().hex}/{sanitize_filename(payload.filename)}"
    return {"direct": True, "url": storage.signed_upload_url(key), "key": key}


async def _temp_copy(course_id: int, file: UploadFile | None, storage_key: str | None, default_name: str) -> tuple[str, str]:
    """Write the upload (form file or direct-to-Storage key) to a temp file.
    Returns (temp path, original filename)."""
    if storage_key:
        if not storage_key.startswith(_upload_prefix(course_id)) or ".." in storage_key:
            raise HTTPException(status_code=400, detail="Unexpected upload key")
        try:
            data = storage.read_bytes(storage.location_for(storage_key))
        except storage.StorageError:
            raise HTTPException(status_code=400, detail="Upload not found")
        name = storage_key.rsplit("/", 1)[-1]
    elif file is not None:
        data = await file.read()
        name = file.filename or default_name
    else:
        raise HTTPException(status_code=422, detail="Send a file or a storage_key")
    suffix = Path(name).suffix or Path(default_name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
    return tmp.name, name


def _discard_upload(storage_key: str | None) -> None:
    if storage_key:
        try:
            storage.delete(storage.location_for(storage_key))
        except storage.StorageError:
            pass


@router.post("/roster")
async def import_roster(
    course_id: int,
    file: UploadFile | None = File(default=None),
    storage_key: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    tmp_path, _ = await _temp_copy(course_id, file, storage_key, "roster.xlsx")
    try:
        rows = parse_roster_xlsx(tmp_path)
    finally:
        os.unlink(tmp_path)
        _discard_upload(storage_key)

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
    file: UploadFile | None = File(default=None),
    storage_key: str | None = Form(default=None),
    assignment_type: str = Form(...),
    workcode: int = Form(...),
    assignment_name: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    tmp_path, _ = await _temp_copy(course_id, file, storage_key, "submissions.zip")
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
        _discard_upload(storage_key)

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
async def import_presentations(
    course_id: int,
    file: UploadFile | None = File(default=None),
    storage_key: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> PresentationImportResult:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    tmp_path, _ = await _temp_copy(course_id, file, storage_key, "presentations.xlsx")
    try:
        rows = parse_presentations_xlsx(tmp_path)
        rows = aggregate_presentation_rows(rows)
    finally:
        os.unlink(tmp_path)
        _discard_upload(storage_key)

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

        if row.bonus:
            db.add(
                StudentComponentOverride(
                    course_id=course_id,
                    student_id=student.id,
                    component="bonus",
                    delta=row.bonus,
                    reason=f"Presentation import ({row.stage})",
                )
            )
            bonus_updates += 1

        imported_rows += 1

    db.commit()
    return PresentationImportResult(imported_rows=imported_rows, bonus_updates=bonus_updates)
