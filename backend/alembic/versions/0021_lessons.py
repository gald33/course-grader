"""Guided lessons: lessons, immutable published versions, per-student
progress (pinned to a version), answer attempts, experiment records, and
commitments with their final-test results.

Downgrade drops these tables and every student's lesson activity with them.
Rolling back the lesson UI does not need it: the tables are additive and the
rest of the app never reads them, so leave the schema in place.

Revision ID: 0021_lessons
Revises: 0020_enrollment_withdrawn
Create Date: 2026-10-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_lessons"
down_revision: Union[str, None] = "0020_enrollment_withdrawn"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = (
    "lessons",
    "lesson_versions",
    "lesson_progress",
    "lesson_attempts",
    "lesson_experiments",
    "lesson_commitments",
)


def upgrade() -> None:
    op.create_table(
        "lessons",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("active_version_id", sa.Integer(), nullable=True),
        sa.Column("colab_url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("fixture_key", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("course_id", "slug", name="uq_lesson_course_slug"),
    )
    op.create_index("ix_lessons_course_id", "lessons", ["course_id"])

    op.create_table(
        "lesson_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("lesson_id", "number", name="uq_lesson_version_number"),
    )
    op.create_index("ix_lesson_versions_lesson_id", "lesson_versions", ["lesson_id"])

    op.create_table(
        "lesson_progress",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "enrollment_id", sa.Integer(), sa.ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("lesson_versions.id"), nullable=False),
        sa.Column("current_step_key", sa.String(length=64), nullable=True),
        sa.Column("viewed_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("acks_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("drafts_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("enrollment_id", "lesson_id", name="uq_lesson_progress_enrollment"),
    )
    op.create_index("ix_lesson_progress_enrollment_id", "lesson_progress", ["enrollment_id"])

    op.create_table(
        "lesson_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "enrollment_id", sa.Integer(), sa.ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("lesson_versions.id"), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("question_key", sa.String(length=64), nullable=False),
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("answer_json", sa.Text(), nullable=True),
        sa.Column("correct", sa.Boolean(), nullable=True),
        sa.Column("after_feedback", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("review_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("enrollment_id", "request_id", name="uq_lesson_attempt_request"),
    )
    op.create_index("ix_lesson_attempts_enrollment_id", "lesson_attempts", ["enrollment_id"])
    op.create_index("ix_lesson_attempts_lesson_question", "lesson_attempts", ["lesson_id", "question_key"])

    op.create_table(
        "lesson_experiments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "enrollment_id", sa.Integer(), sa.ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("lesson_versions.id"), nullable=False),
        sa.Column("run_uuid", sa.String(length=36), nullable=False),
        sa.Column("depth_kind", sa.String(length=16), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=True),
        sa.Column("training_examples", sa.Integer(), nullable=True),
        sa.Column("train_accuracy", sa.Float(), nullable=True),
        sa.Column("validation_accuracy", sa.Float(), nullable=True),
        sa.Column("baseline_validation", sa.Float(), nullable=True),
        sa.Column("hypothesis", sa.Text(), nullable=False, server_default=""),
        sa.Column("first_hypothesis", sa.Text(), nullable=True),
        sa.Column("first_hypothesis_at", sa.DateTime(), nullable=True),
        sa.Column("observation", sa.Text(), nullable=False, server_default=""),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("provenance", sa.String(length=32), nullable=False, server_default="student_entered"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("enrollment_id", "run_uuid", name="uq_lesson_experiment_run"),
    )
    op.create_index("ix_lesson_experiments_enrollment_id", "lesson_experiments", ["enrollment_id"])

    op.create_table(
        "lesson_commitments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "enrollment_id", sa.Integer(), sa.ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("lesson_versions.id"), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("run_uuid", sa.String(length=36), nullable=True),
        sa.Column("depth_kind", sa.String(length=16), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=True),
        sa.Column("training_examples", sa.Integer(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("committed_at", sa.DateTime(), nullable=False),
        sa.Column("after_final_seen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("final_accuracy", sa.Float(), nullable=True),
        sa.Column("final_precision", sa.Float(), nullable=True),
        sa.Column("final_recall", sa.Float(), nullable=True),
        sa.Column("final_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("final_recorded_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("enrollment_id", "request_id", name="uq_lesson_commitment_request"),
    )
    op.create_index("ix_lesson_commitments_enrollment_id", "lesson_commitments", ["enrollment_id"])

    if op.get_bind().dialect.name == "postgresql":
        # Same protection as 0010: keep them out of Supabase's public REST API.
        for table in TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Destructive: drops every student's lesson progress, answers, experiments
    # and commitments. Not part of rolling back UI code.
    op.drop_index("ix_lesson_commitments_enrollment_id", table_name="lesson_commitments")
    op.drop_table("lesson_commitments")
    op.drop_index("ix_lesson_experiments_enrollment_id", table_name="lesson_experiments")
    op.drop_table("lesson_experiments")
    op.drop_index("ix_lesson_attempts_lesson_question", table_name="lesson_attempts")
    op.drop_index("ix_lesson_attempts_enrollment_id", table_name="lesson_attempts")
    op.drop_table("lesson_attempts")
    op.drop_index("ix_lesson_progress_enrollment_id", table_name="lesson_progress")
    op.drop_table("lesson_progress")
    op.drop_index("ix_lesson_versions_lesson_id", table_name="lesson_versions")
    op.drop_table("lesson_versions")
    op.drop_index("ix_lessons_course_id", table_name="lessons")
    op.drop_table("lessons")
