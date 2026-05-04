from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    year: Mapped[int] = mapped_column(Integer)
    semester: Mapped[str] = mapped_column(String(64))
    attendance_threshold: Mapped[float] = mapped_column(Float, default=80.0)

    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="course", cascade="all, delete-orphan")
    assignments: Mapped[list[Assignment]] = relationship(back_populates="course", cascade="all, delete-orphan")
    submissions: Mapped[list[Submission]] = relationship(back_populates="course", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("code", "year", "semester", name="uq_course_identity"),)


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    national_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))

    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="student", cascade="all, delete-orphan")
    memberships: Mapped[list[SubmissionMember]] = relationship(back_populates="student", cascade="all, delete-orphan")


class Enrollment(Base):
    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    attendance_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    attendance_exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    bonus_points: Mapped[float] = mapped_column(Float, default=0.0)

    course: Mapped[Course] = relationship(back_populates="enrollments")
    student: Mapped[Student] = relationship(back_populates="enrollments")

    __table_args__ = (UniqueConstraint("course_id", "student_id", name="uq_enrollment_course_student"),)


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    workcode: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255))
    assignment_type: Mapped[str] = mapped_column(String(32), index=True)

    course: Mapped[Course] = relationship(back_populates="assignments")
    submissions: Mapped[list[Submission]] = relationship(back_populates="assignment", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("course_id", "workcode", "assignment_type", name="uq_assignment_course_workcode_type"),)


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    group_identifier: Mapped[str] = mapped_column(String(255), index=True)
    originality_score_filename: Mapped[float | None] = mapped_column(Float, nullable=True)
    originality_score_pdf: Mapped[float | None] = mapped_column(Float, nullable=True)
    originality_mismatch: Mapped[bool] = mapped_column(Boolean, default=False)
    notes_private: Mapped[str] = mapped_column(Text, default="")
    feedback_student: Mapped[str] = mapped_column(Text, default="")
    consistency_summary: Mapped[str] = mapped_column(Text, default="")
    consistency_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    missing_report_flag: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    missing_data_flag: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    missing_code_flag: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    manual_grade: Mapped[float | None] = mapped_column(Float, nullable=True)
    pinned_run_id: Mapped[int | None] = mapped_column(ForeignKey("notebook_runs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    course: Mapped[Course] = relationship(back_populates="submissions")
    assignment: Mapped[Assignment] = relationship(back_populates="submissions")
    members: Mapped[list[SubmissionMember]] = relationship(back_populates="submission", cascade="all, delete-orphan")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="submission", cascade="all, delete-orphan")
    snapshots: Mapped[list[ColabSnapshot]] = relationship(back_populates="submission", cascade="all, delete-orphan")
    runs: Mapped[list[NotebookRun]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        foreign_keys="NotebookRun.submission_id",
    )

    __table_args__ = (UniqueConstraint("assignment_id", "group_identifier", name="uq_submission_assignment_group"),)


class SubmissionMember(Base):
    __tablename__ = "submission_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)

    submission: Mapped[Submission] = relationship(back_populates="members")
    student: Mapped[Student] = relationship(back_populates="memberships")

    __table_args__ = (UniqueConstraint("submission_id", "student_id", name="uq_submission_member"),)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(255), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    submission: Mapped[Submission | None] = relationship(back_populates="artifacts")


class ColabSnapshot(Base):
    __tablename__ = "colab_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, default="")

    submission: Mapped[Submission] = relationship(back_populates="snapshots")


class NotebookRun(Base):
    __tablename__ = "notebook_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("colab_snapshots.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="QUEUED")
    mode: Mapped[str] = mapped_column(String(32), default="snapshot")
    ok_cells: Mapped[int] = mapped_column(Integer, default=0)
    failed_cells: Mapped[int] = mapped_column(Integer, default=0)
    run_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    penalty_multiplier: Mapped[float] = mapped_column(Float, default=0.0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str] = mapped_column(Text, default="")
    log_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True)
    executed_notebook_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True)
    executed_html_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    submission: Mapped[Submission] = relationship(back_populates="runs", foreign_keys=[submission_id])


class RubricDimensionScore(Base):
    __tablename__ = "rubric_dimension_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    component: Mapped[str] = mapped_column(String(64), index=True)
    dimension_key: Mapped[str] = mapped_column(String(128), index=True)
    raw_score: Mapped[float] = mapped_column(Float)
    adjusted_score: Mapped[float] = mapped_column(Float)

    __table_args__ = (UniqueConstraint("submission_id", "component", "dimension_key", name="uq_rubric_component_dim"),)


class PresentationScore(Base):
    __tablename__ = "presentation_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(16), index=True)
    clarity: Mapped[float] = mapped_column(Float, default=0.0)
    complexity: Mapped[float] = mapped_column(Float, default=0.0)
    qa_answers: Mapped[float] = mapped_column(Float, default=0.0)
    elegance: Mapped[float] = mapped_column(Float, default=0.0)
    subjective_impression: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (UniqueConstraint("course_id", "student_id", "stage", name="uq_presentation_student_stage"),)


class StudentComponentOverride(Base):
    __tablename__ = "student_component_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), nullable=True, index=True)
    component: Mapped[str] = mapped_column(String(64), index=True)
    delta: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CurveRevision(Base):
    __tablename__ = "curve_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    mapping_json: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("course_id", "revision_number", name="uq_curve_revision_num"),)
