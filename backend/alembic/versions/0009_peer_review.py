"""Peer review: teams, sessions, review rounds, presentations, versioned
rubrics, individual reviews, review obligations, and student review tokens.

Revision ID: 0009_peer_review
Revises: 0008_rename_initial_stage_to_presentation
Create Date: 2026-10-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_peer_review"
down_revision: Union[str, None] = "0008_rename_initial_stage_to_presentation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("enrollments") as batch:
        batch.add_column(sa.Column("review_token", sa.String(length=64), nullable=True))
        batch.create_index("ix_enrollments_review_token", ["review_token"], unique=True)

    op.create_table(
        "class_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("held_on", sa.Date(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.UniqueConstraint("course_id", "number", name="uq_class_session_number"),
    )
    op.create_index("ix_class_sessions_course_id", "class_sessions", ["course_id"])

    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("project_title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("course_id", "name", name="uq_team_course_name"),
    )
    op.create_index("ix_teams_course_id", "teams", ["course_id"])

    op.create_table(
        "team_memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=True),
        sa.Column("end_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_team_memberships_course_id", "team_memberships", ["course_id"])
    op.create_index("ix_team_memberships_team_id", "team_memberships", ["team_id"])
    op.create_index("ix_team_memberships_student_id", "team_memberships", ["student_id"])
    op.create_index(
        "uq_team_membership_active",
        "team_memberships",
        ["course_id", "student_id"],
        unique=True,
        sqlite_where=sa.text("end_at IS NULL"),
        postgresql_where=sa.text("end_at IS NULL"),
    )

    op.create_table(
        "peer_rubric_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("criteria_json", sa.Text(), nullable=False),
        sa.Column("scale_json", sa.Text(), nullable=False),
        sa.Column("prompts_json", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("frozen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("course_id", "kind", "version", name="uq_peer_rubric_version"),
    )
    op.create_index("ix_peer_rubric_versions_course_id", "peer_rubric_versions", ["course_id"])

    op.create_table(
        "review_rounds",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("sessions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("selection_deadline", sa.DateTime(), nullable=True),
        sa.Column("review_deadline", sa.DateTime(), nullable=True),
        sa.Column("rubric_version_id", sa.Integer(), sa.ForeignKey("peer_rubric_versions.id"), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("target_mean", sa.Float(), nullable=False, server_default="80"),
        sa.Column("target_std", sa.Float(), nullable=False, server_default="10"),
        sa.Column("missing_review_policy", sa.String(length=16), nullable=False, server_default="missing"),
        sa.Column("participation_factor", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("llm_enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("course_id", "number", name="uq_review_round_number"),
    )
    op.create_index("ix_review_rounds_course_id", "review_rounds", ["course_id"])

    op.create_table(
        "presentations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("round_id", sa.Integer(), sa.ForeignKey("review_rounds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_number", sa.Integer(), nullable=True),
        sa.Column("original_session_number", sa.Integer(), nullable=True),
        sa.Column("assignment_source", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="scheduled"),
        sa.Column("review_open", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("demo_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("materials_text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "slides_artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("round_id", "team_id", name="uq_presentation_round_team"),
    )
    op.create_index("ix_presentations_round_id", "presentations", ["round_id"])
    op.create_index("ix_presentations_team_id", "presentations", ["team_id"])

    op.create_table(
        "presentation_moves",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "presentation_id", sa.Integer(), sa.ForeignKey("presentations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("from_session", sa.Integer(), nullable=True),
        sa.Column("to_session", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("actor", sa.String(length=16), nullable=False, server_default="instructor"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_presentation_moves_presentation_id", "presentation_moves", ["presentation_id"])

    op.create_table(
        "review_round_roster",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("round_id", sa.Integer(), sa.ForeignKey("review_rounds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("round_id", "student_id", name="uq_round_roster_student"),
    )
    op.create_index("ix_review_round_roster_round_id", "review_round_roster", ["round_id"])
    op.create_index("ix_review_round_roster_student_id", "review_round_roster", ["student_id"])

    op.create_table(
        "review_obligations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("round_id", sa.Integer(), sa.ForeignKey("review_rounds.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "presentation_id", sa.Integer(), sa.ForeignKey("presentations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exempt", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("exempt_reason", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("presentation_id", "student_id", name="uq_obligation_presentation_student"),
    )
    op.create_index("ix_review_obligations_round_id", "review_obligations", ["round_id"])
    op.create_index("ix_review_obligations_presentation_id", "review_obligations", ["presentation_id"])
    op.create_index("ix_review_obligations_student_id", "review_obligations", ["student_id"])

    op.create_table(
        "peer_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("round_id", sa.Integer(), sa.ForeignKey("review_rounds.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "presentation_id", sa.Integer(), sa.ForeignKey("presentations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "rubric_version_id", sa.Integer(), sa.ForeignKey("peer_rubric_versions.id"), nullable=False
        ),
        sa.Column("reviewer_kind", sa.String(length=16), nullable=False, server_default="student"),
        sa.Column(
            "reviewer_student_id", sa.Integer(), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("reviewer_team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scores_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("responses_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("llm_model", sa.String(length=64), nullable=True),
        sa.Column("llm_rationale_json", sa.Text(), nullable=True),
        sa.Column("excluded", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("exclusion_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("excluded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("presentation_id", "reviewer_student_id", name="uq_peer_review_student"),
        sa.CheckConstraint(
            "(reviewer_kind = 'student' AND reviewer_student_id IS NOT NULL)"
            " OR (reviewer_kind = 'llm' AND reviewer_student_id IS NULL)",
            name="ck_peer_review_reviewer",
        ),
    )
    op.create_index("ix_peer_reviews_round_id", "peer_reviews", ["round_id"])
    op.create_index("ix_peer_reviews_presentation_id", "peer_reviews", ["presentation_id"])
    op.create_index("ix_peer_reviews_reviewer_student_id", "peer_reviews", ["reviewer_student_id"])
    op.create_index(
        "uq_peer_review_llm",
        "peer_reviews",
        ["presentation_id"],
        unique=True,
        sqlite_where=sa.text("reviewer_kind = 'llm'"),
        postgresql_where=sa.text("reviewer_kind = 'llm'"),
    )


def downgrade() -> None:
    op.drop_table("peer_reviews")
    op.drop_table("review_obligations")
    op.drop_table("review_round_roster")
    op.drop_table("presentation_moves")
    op.drop_table("presentations")
    op.drop_table("review_rounds")
    op.drop_table("peer_rubric_versions")
    op.drop_table("team_memberships")
    op.drop_table("teams")
    op.drop_table("class_sessions")
    with op.batch_alter_table("enrollments") as batch:
        batch.drop_index("ix_enrollments_review_token")
        batch.drop_column("review_token")
