"""Initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-02-19 15:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("semester", sa.String(length=64), nullable=False),
        sa.Column("attendance_threshold", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "year", "semester", name="uq_course_identity"),
    )
    op.create_index(op.f("ix_courses_code"), "courses", ["code"], unique=False)

    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("national_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("national_id"),
    )
    op.create_index(op.f("ix_students_national_id"), "students", ["national_id"], unique=False)

    op.create_table(
        "assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("workcode", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("assignment_type", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "workcode", "assignment_type", name="uq_assignment_course_workcode_type"),
    )
    op.create_index(op.f("ix_assignments_assignment_type"), "assignments", ["assignment_type"], unique=False)
    op.create_index(op.f("ix_assignments_course_id"), "assignments", ["course_id"], unique=False)
    op.create_index(op.f("ix_assignments_workcode"), "assignments", ["workcode"], unique=False)

    op.create_table(
        "curve_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("mapping_json", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "revision_number", name="uq_curve_revision_num"),
    )
    op.create_index(op.f("ix_curve_revisions_course_id"), "curve_revisions", ["course_id"], unique=False)

    op.create_table(
        "enrollments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("attendance_percent", sa.Float(), nullable=True),
        sa.Column("attendance_exempt", sa.Boolean(), nullable=False),
        sa.Column("bonus_points", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "student_id", name="uq_enrollment_course_student"),
    )
    op.create_index(op.f("ix_enrollments_course_id"), "enrollments", ["course_id"], unique=False)
    op.create_index(op.f("ix_enrollments_student_id"), "enrollments", ["student_id"], unique=False)

    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=False),
        sa.Column("group_identifier", sa.String(length=255), nullable=False),
        sa.Column("originality_score_filename", sa.Float(), nullable=True),
        sa.Column("originality_score_pdf", sa.Float(), nullable=True),
        sa.Column("originality_mismatch", sa.Boolean(), nullable=False),
        sa.Column("notes_private", sa.Text(), nullable=False),
        sa.Column("feedback_student", sa.Text(), nullable=False),
        sa.Column("consistency_summary", sa.Text(), nullable=False),
        sa.Column("consistency_flags_json", sa.Text(), nullable=False),
        sa.Column("pinned_run_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "group_identifier", name="uq_submission_assignment_group"),
    )
    op.create_index(op.f("ix_submissions_assignment_id"), "submissions", ["assignment_id"], unique=False)
    op.create_index(op.f("ix_submissions_course_id"), "submissions", ["course_id"], unique=False)
    op.create_index(op.f("ix_submissions_group_identifier"), "submissions", ["group_identifier"], unique=False)

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_artifacts_kind"), "artifacts", ["kind"], unique=False)
    op.create_index(op.f("ix_artifacts_submission_id"), "artifacts", ["submission_id"], unique=False)

    op.create_table(
        "colab_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("file_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.Column("artifact_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_colab_snapshots_submission_id"), "colab_snapshots", ["submission_id"], unique=False)

    op.create_table(
        "notebook_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("ok_cells", sa.Integer(), nullable=False),
        sa.Column("failed_cells", sa.Integer(), nullable=False),
        sa.Column("run_ratio", sa.Float(), nullable=False),
        sa.Column("penalty_multiplier", sa.Float(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=False),
        sa.Column("log_artifact_id", sa.Integer(), nullable=True),
        sa.Column("executed_notebook_artifact_id", sa.Integer(), nullable=True),
        sa.Column("executed_html_artifact_id", sa.Integer(), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["executed_html_artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["executed_notebook_artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["log_artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["colab_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notebook_runs_snapshot_id"), "notebook_runs", ["snapshot_id"], unique=False)
    op.create_index(op.f("ix_notebook_runs_submission_id"), "notebook_runs", ["submission_id"], unique=False)

    op.create_table(
        "presentation_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("clarity", sa.Float(), nullable=False),
        sa.Column("complexity", sa.Float(), nullable=False),
        sa.Column("qa_answers", sa.Float(), nullable=False),
        sa.Column("elegance", sa.Float(), nullable=False),
        sa.Column("subjective_impression", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "student_id", "stage", name="uq_presentation_student_stage"),
    )
    op.create_index(op.f("ix_presentation_scores_course_id"), "presentation_scores", ["course_id"], unique=False)
    op.create_index(op.f("ix_presentation_scores_stage"), "presentation_scores", ["stage"], unique=False)
    op.create_index(op.f("ix_presentation_scores_student_id"), "presentation_scores", ["student_id"], unique=False)

    op.create_table(
        "rubric_dimension_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("component", sa.String(length=64), nullable=False),
        sa.Column("dimension_key", sa.String(length=128), nullable=False),
        sa.Column("raw_score", sa.Float(), nullable=False),
        sa.Column("adjusted_score", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id", "component", "dimension_key", name="uq_rubric_component_dim"),
    )
    op.create_index(op.f("ix_rubric_dimension_scores_component"), "rubric_dimension_scores", ["component"], unique=False)
    op.create_index(op.f("ix_rubric_dimension_scores_dimension_key"), "rubric_dimension_scores", ["dimension_key"], unique=False)
    op.create_index(op.f("ix_rubric_dimension_scores_submission_id"), "rubric_dimension_scores", ["submission_id"], unique=False)

    op.create_table(
        "student_component_overrides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=True),
        sa.Column("component", sa.String(length=64), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_student_component_overrides_component"), "student_component_overrides", ["component"], unique=False)
    op.create_index(op.f("ix_student_component_overrides_course_id"), "student_component_overrides", ["course_id"], unique=False)
    op.create_index(op.f("ix_student_component_overrides_student_id"), "student_component_overrides", ["student_id"], unique=False)
    op.create_index(op.f("ix_student_component_overrides_submission_id"), "student_component_overrides", ["submission_id"], unique=False)

    op.create_table(
        "submission_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id", "student_id", name="uq_submission_member"),
    )
    op.create_index(op.f("ix_submission_members_student_id"), "submission_members", ["student_id"], unique=False)
    op.create_index(op.f("ix_submission_members_submission_id"), "submission_members", ["submission_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_submission_members_submission_id"), table_name="submission_members")
    op.drop_index(op.f("ix_submission_members_student_id"), table_name="submission_members")
    op.drop_table("submission_members")

    op.drop_index(op.f("ix_student_component_overrides_submission_id"), table_name="student_component_overrides")
    op.drop_index(op.f("ix_student_component_overrides_student_id"), table_name="student_component_overrides")
    op.drop_index(op.f("ix_student_component_overrides_course_id"), table_name="student_component_overrides")
    op.drop_index(op.f("ix_student_component_overrides_component"), table_name="student_component_overrides")
    op.drop_table("student_component_overrides")

    op.drop_index(op.f("ix_rubric_dimension_scores_submission_id"), table_name="rubric_dimension_scores")
    op.drop_index(op.f("ix_rubric_dimension_scores_dimension_key"), table_name="rubric_dimension_scores")
    op.drop_index(op.f("ix_rubric_dimension_scores_component"), table_name="rubric_dimension_scores")
    op.drop_table("rubric_dimension_scores")

    op.drop_index(op.f("ix_presentation_scores_student_id"), table_name="presentation_scores")
    op.drop_index(op.f("ix_presentation_scores_stage"), table_name="presentation_scores")
    op.drop_index(op.f("ix_presentation_scores_course_id"), table_name="presentation_scores")
    op.drop_table("presentation_scores")

    op.drop_index(op.f("ix_notebook_runs_submission_id"), table_name="notebook_runs")
    op.drop_index(op.f("ix_notebook_runs_snapshot_id"), table_name="notebook_runs")
    op.drop_table("notebook_runs")

    op.drop_index(op.f("ix_colab_snapshots_submission_id"), table_name="colab_snapshots")
    op.drop_table("colab_snapshots")

    op.drop_index(op.f("ix_artifacts_submission_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_kind"), table_name="artifacts")
    op.drop_table("artifacts")

    op.drop_index(op.f("ix_submissions_group_identifier"), table_name="submissions")
    op.drop_index(op.f("ix_submissions_course_id"), table_name="submissions")
    op.drop_index(op.f("ix_submissions_assignment_id"), table_name="submissions")
    op.drop_table("submissions")

    op.drop_index(op.f("ix_enrollments_student_id"), table_name="enrollments")
    op.drop_index(op.f("ix_enrollments_course_id"), table_name="enrollments")
    op.drop_table("enrollments")

    op.drop_index(op.f("ix_curve_revisions_course_id"), table_name="curve_revisions")
    op.drop_table("curve_revisions")

    op.drop_index(op.f("ix_assignments_workcode"), table_name="assignments")
    op.drop_index(op.f("ix_assignments_course_id"), table_name="assignments")
    op.drop_index(op.f("ix_assignments_assignment_type"), table_name="assignments")
    op.drop_table("assignments")

    op.drop_index(op.f("ix_students_national_id"), table_name="students")
    op.drop_table("students")

    op.drop_index(op.f("ix_courses_code"), table_name="courses")
    op.drop_table("courses")
