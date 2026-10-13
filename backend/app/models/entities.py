from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
    true,
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
    # Student account (Supabase Auth): the email is the username. Stored
    # lowercase; invited/activated track the invite-to-set-password flow.
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, unique=True, index=True)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    account_activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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
    # Capability token for the student-facing peer-review page (/r/<token>).
    # Generated on demand by the instructor; the only student credential.
    review_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)

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
    missing_report_flag: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    missing_data_flag: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    missing_code_flag: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    manual_grade: Mapped[float | None] = mapped_column(Float, nullable=True)
    project_llm_review_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_review_json: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # True once the grader has touched/approved this score. LLM auto-applied
    # scores start as False; manual dot clicks and explicit ✓ taps both flip
    # this to True.
    approved: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

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


# ---------------------------------------------------------------------------
# Peer review
#
# Teams present once per review round; every student individually reviews the
# other teams' presentations. Reviewer identity is stored (for participation
# tracking and moderation) but never leaves the instructor API.
# ---------------------------------------------------------------------------


class ClassSession(Base):
    __tablename__ = "class_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    held_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="")

    __table_args__ = (UniqueConstraint("course_id", "number", name="uq_class_session_number"),)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    project_title: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    memberships: Mapped[list[TeamMembership]] = relationship(back_populates="team", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("course_id", "name", name="uq_team_course_name"),)


class TeamMembership(Base):
    """Membership history. Moving a student ends the old row instead of
    rewriting it, so past rounds keep the team the student actually had."""

    __tablename__ = "team_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    team: Mapped[Team] = relationship(back_populates="memberships")
    student: Mapped[Student] = relationship()

    __table_args__ = (
        Index(
            "uq_team_membership_active",
            "course_id",
            "student_id",
            unique=True,
            sqlite_where=text("end_at IS NULL"),
            postgresql_where=text("end_at IS NULL"),
        ),
    )


class PeerRubricVersion(Base):
    """Immutable once frozen. A round pins the version that was current when
    its reviews opened; later edits create a new version instead."""

    __tablename__ = "peer_rubric_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # progress | final
    version: Mapped[int] = mapped_column(Integer)
    criteria_json: Mapped[str] = mapped_column(Text)  # [{key, label, description, weight}]
    scale_json: Mapped[str] = mapped_column(Text)  # [{value, label}]
    prompts_json: Mapped[str] = mapped_column(Text)  # [{key, label, required}]
    instructions: Mapped[str] = mapped_column(Text, default="")
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("course_id", "kind", "version", name="uq_peer_rubric_version"),)


class ReviewRound(Base):
    __tablename__ = "review_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # progress | final
    title: Mapped[str] = mapped_column(String(255), default="")
    # Regular presentation sessions with capacities: [{"number": 2, "capacity": 4}, ...]
    sessions_json: Mapped[str] = mapped_column(Text, default="[]")
    # draft → scheduling → reviewing → closed (release is tracked by released_at)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    selection_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rubric_version_id: Mapped[int | None] = mapped_column(ForeignKey("peer_rubric_versions.id"), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Scoring configuration (per round; one assignment grade per round)
    target_mean: Mapped[float] = mapped_column(Float, default=80.0)
    target_std: Mapped[float] = mapped_column(Float, default=10.0)
    missing_review_policy: Mapped[str] = mapped_column(String(16), default="missing")  # missing | zero
    participation_factor: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    rubric_version: Mapped[PeerRubricVersion | None] = relationship()
    presentations: Mapped[list[Presentation]] = relationship(back_populates="round", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("course_id", "number", name="uq_review_round_number"),)


class Presentation(Base):
    """One team's presentation in one round. Moving it (postpone, swap,
    override) only changes session_number — the round and every review stay."""

    __tablename__ = "presentations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("review_rounds.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    session_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_session_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assignment_source: Mapped[str] = mapped_column(String(16), default="")  # volunteer | random | instructor
    status: Mapped[str] = mapped_column(String(16), default="scheduled")  # scheduled | postponed
    review_open: Mapped[bool] = mapped_column(Boolean, default=False)
    demo_url: Mapped[str] = mapped_column(Text, default="")
    materials_text: Mapped[str] = mapped_column(Text, default="")
    slides_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    round: Mapped[ReviewRound] = relationship(back_populates="presentations")
    team: Mapped[Team] = relationship()

    __table_args__ = (UniqueConstraint("round_id", "team_id", name="uq_presentation_round_team"),)


class PresentationMove(Base):
    __tablename__ = "presentation_moves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    presentation_id: Mapped[int] = mapped_column(ForeignKey("presentations.id", ondelete="CASCADE"), index=True)
    from_session: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_session: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16))  # volunteer | random | override | postpone | swap
    actor: Mapped[str] = mapped_column(String(16), default="instructor")  # instructor | student
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReviewRoundRoster(Base):
    """Snapshot of each student's team when the round opened for reviewing.
    Eligibility and the team score a student receives come from here, so later
    team changes don't rewrite past rounds."""

    __tablename__ = "review_round_roster"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("review_rounds.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (UniqueConstraint("round_id", "student_id", name="uq_round_roster_student"),)


class ReviewObligation(Base):
    __tablename__ = "review_obligations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("review_rounds.id", ondelete="CASCADE"), index=True)
    presentation_id: Mapped[int] = mapped_column(ForeignKey("presentations.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    exempt_reason: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (UniqueConstraint("presentation_id", "student_id", name="uq_obligation_presentation_student"),)


class PeerReview(Base):
    __tablename__ = "peer_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("review_rounds.id", ondelete="CASCADE"), index=True)
    presentation_id: Mapped[int] = mapped_column(ForeignKey("presentations.id", ondelete="CASCADE"), index=True)
    rubric_version_id: Mapped[int] = mapped_column(ForeignKey("peer_rubric_versions.id"))
    reviewer_kind: Mapped[str] = mapped_column(String(16), default="student")  # student | llm
    reviewer_student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=True, index=True
    )
    reviewer_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    scores_json: Mapped[str] = mapped_column(Text, default="{}")
    responses_json: Mapped[str] = mapped_column(Text, default="{}")
    llm_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_rationale_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Moderation: excluded reviews stay stored but are left out of aggregation.
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    exclusion_reason: Mapped[str] = mapped_column(Text, default="")
    excluded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        # One review per student per presentation. NULLs are distinct, so the
        # LLM row (no student) is covered by the partial index below instead.
        UniqueConstraint("presentation_id", "reviewer_student_id", name="uq_peer_review_student"),
        Index(
            "uq_peer_review_llm",
            "presentation_id",
            unique=True,
            sqlite_where=text("reviewer_kind = 'llm'"),
            postgresql_where=text("reviewer_kind = 'llm'"),
        ),
        CheckConstraint(
            "(reviewer_kind = 'student' AND reviewer_student_id IS NOT NULL)"
            " OR (reviewer_kind = 'llm' AND reviewer_student_id IS NULL)",
            name="ck_peer_review_reviewer",
        ),
    )


class Job(Base):
    """Background job queue (replaces Celery + Redis). The API inserts rows;
    `python -m app.tasks.worker` claims them with an atomic status update."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    args_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | running | succeeded | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    worker: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("ix_jobs_status_id", "status", "id"),)
