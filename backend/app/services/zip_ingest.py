from __future__ import annotations

import json
import mimetypes
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Artifact, Assignment, Enrollment, Student, Submission, SubmissionMember
from app.services.filename_parser import group_identifier_from_ids, parse_filename
from app.services import storage
from app.utils.text import normalize_id, sanitize_filename


_DATA_EXTS = {
    ".csv",
    ".tsv",
    ".xlsx",
    ".xls",
    ".json",
    ".parquet",
    ".pkl",
    ".npy",
    ".npz",
    ".sqlite",
    ".db",
}
# Notebooks aren't data per se but they're auxiliary code, not the primary doc.
_CODE_EXTS = {".ipynb", ".py"}
_REPORT_HINTS = ("report", "דו", "דוח")


def _classify_kind(
    db: Session,
    submission_id: int,
    filename: str,
    assignment_type: str,
    is_originality: bool = False,
) -> str:
    """Pick the right artifact kind for a file ingested from a submission ZIP."""
    if is_originality:
        return "originality_pdf"
    name = filename.lower()
    ext = Path(name).suffix
    if ext in _DATA_EXTS:
        return "data_file"
    if ext == ".zip":
        return "data_file"  # nested zips (datasets) — not the primary deliverable
    if ext in _CODE_EXTS:
        return "code_file"
    if ext == ".pdf" and assignment_type == "PROJECT":
        # Pick the project report — by name hint, or the first PDF on this submission
        if any(h in name for h in _REPORT_HINTS):
            return "project_report_pdf"
        existing_report = db.scalar(
            select(Artifact.id).where(
                Artifact.submission_id == submission_id,
                Artifact.kind == "project_report_pdf",
            )
        )
        if existing_report is None:
            return "project_report_pdf"
    return "submission_file"


@dataclass
class ZipIngestResult:
    created_submissions: int
    updated_submissions: int
    created_students: int
    stored_artifacts: int


def _get_or_create_student(db: Session, course_id: int, national_id: str) -> tuple[Student, bool]:
    student = db.scalar(select(Student).where(Student.national_id == national_id))
    created = False
    if student is None:
        student = Student(national_id=national_id, name=f"Student {national_id}")
        db.add(student)
        db.flush()
        created = True

    enrollment = db.scalar(
        select(Enrollment).where(Enrollment.course_id == course_id, Enrollment.student_id == student.id)
    )
    if enrollment is None:
        db.add(Enrollment(course_id=course_id, student_id=student.id))
        db.flush()

    return student, created


def _assignment(db: Session, course_id: int, assignment_type: str, workcode: int, name: str | None) -> Assignment:
    assignment = db.scalar(
        select(Assignment).where(
            Assignment.course_id == course_id,
            Assignment.assignment_type == assignment_type,
            Assignment.workcode == workcode,
        )
    )
    if assignment:
        if name:
            assignment.name = name
        return assignment

    assignment = Assignment(
        course_id=course_id,
        assignment_type=assignment_type,
        workcode=workcode,
        name=name or f"{assignment_type} WorkCode {workcode}",
    )
    db.add(assignment)
    db.flush()
    return assignment


def ingest_submission_zip(
    db: Session,
    course_id: int,
    assignment_type: str,
    zip_path: str,
    fallback_workcode: int,
    assignment_name: str | None,
) -> ZipIngestResult:
    created_submissions = 0
    updated_submissions = 0
    created_students = 0
    stored_artifacts = 0

    assignment_cache: dict[int, Assignment] = {}
    latest_submission_for_assignment: dict[int, Submission] = {}

    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            filename = Path(member.filename).name
            parsed = parse_filename(filename)
            if not parsed.ids and not parsed.is_originality_pdf:
                continue

            workcode = parsed.workcode or fallback_workcode
            assignment = assignment_cache.get(workcode)
            if assignment is None:
                assignment = _assignment(db, course_id, assignment_type, workcode, assignment_name)
                assignment_cache[workcode] = assignment

            submission: Submission | None = None
            group_identifier = group_identifier_from_ids(parsed.ids)
            if parsed.ids:
                submission = db.scalar(
                    select(Submission).where(
                        Submission.assignment_id == assignment.id,
                        Submission.group_identifier == group_identifier,
                    )
                )

                if submission is None:
                    submission = Submission(
                        course_id=course_id,
                        assignment_id=assignment.id,
                        group_identifier=group_identifier,
                        originality_score_filename=parsed.originality_score,
                    )
                    db.add(submission)
                    db.flush()
                    created_submissions += 1
                else:
                    updated_submissions += 1
                    if parsed.originality_score is not None:
                        submission.originality_score_filename = parsed.originality_score

                latest_submission_for_assignment[assignment.id] = submission

                for sid in parsed.ids:
                    student, was_created = _get_or_create_student(db, course_id, sid)
                    created_students += int(was_created)
                    exists = db.scalar(
                        select(SubmissionMember).where(
                            SubmissionMember.submission_id == submission.id,
                            SubmissionMember.student_id == student.id,
                        )
                    )
                    if not exists:
                        db.add(SubmissionMember(submission_id=submission.id, student_id=student.id))

            elif parsed.is_originality_pdf:
                submission = latest_submission_for_assignment.get(assignment.id)

            if submission is None:
                continue

            safe_name = sanitize_filename(filename)
            mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            location = storage.save(
                f"uploads/{course_id}/{assignment.id}/{submission.id}/{safe_name}", zf.read(member), mime_type
            )
            kind = _classify_kind(db, submission.id, filename, assignment_type, parsed.is_originality_pdf)

            artifact = Artifact(
                submission_id=submission.id,
                kind=kind,
                filename=filename,
                path=location,
                mime_type=mime_type,
                size_bytes=member.file_size,
                metadata_json=json.dumps({"source_zip": Path(zip_path).name}),
            )
            db.add(artifact)
            db.flush()
            stored_artifacts += 1

            if parsed.is_originality_pdf and parsed.originality_score is not None:
                submission.originality_score_filename = parsed.originality_score

    db.commit()
    return ZipIngestResult(
        created_submissions=created_submissions,
        updated_submissions=updated_submissions,
        created_students=created_students,
        stored_artifacts=stored_artifacts,
    )
