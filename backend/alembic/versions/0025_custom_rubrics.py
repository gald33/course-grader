"""Custom rubrics: per-assignment rubrics (ordered criteria), the
autograder's per-run criterion results, and the instructor's per-criterion
overrides.

Additive only: four new tables, nothing existing is altered. Every foreign
key to a rubric, criterion or submission cascades on delete (the app also
deletes a criterion's results and overrides explicitly, since SQLite does not
enforce foreign keys); run_id is set null when a run goes. Criterion
positions are not unique, so a reorder can't trip a constraint midway. Assignments
without a rubric keep the fixed code dimensions. Downgrade drops the tables
and every custom rubric, result and override with them.

Revision ID: 0025_custom_rubrics
Revises: 0024_lessons
Create Date: 2026-10-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_custom_rubrics"
down_revision: Union[str, None] = "0024_lessons"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("assignment_rubrics", "rubric_criteria", "criterion_results", "criterion_overrides")


def upgrade() -> None:
    op.create_table(
        "assignment_rubrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "copied_from_rubric_id",
            sa.Integer(),
            sa.ForeignKey("assignment_rubrics.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_assignment_rubrics_assignment_id", "assignment_rubrics", ["assignment_id"], unique=True)

    op.create_table(
        "rubric_criteria",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rubric_id", sa.Integer(), sa.ForeignKey("assignment_rubrics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("max_points", sa.Float(), nullable=False),
        sa.Column("levels_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_rubric_criteria_rubric_position", "rubric_criteria", ["rubric_id", "position"])

    op.create_table(
        "criterion_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("criterion_id", sa.Integer(), sa.ForeignKey("rubric_criteria.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("notebook_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_criterion_results_submission_criterion", "criterion_results", ["submission_id", "criterion_id"]
    )
    op.create_index("ix_criterion_results_criterion_id", "criterion_results", ["criterion_id"])
    op.create_index("ix_criterion_results_run_id", "criterion_results", ["run_id"])

    op.create_table(
        "criterion_overrides",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("criterion_id", sa.Integer(), sa.ForeignKey("rubric_criteria.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("submission_id", "criterion_id", name="uq_criterion_override"),
    )
    op.create_index("ix_criterion_overrides_submission_id", "criterion_overrides", ["submission_id"])
    op.create_index("ix_criterion_overrides_criterion_id", "criterion_overrides", ["criterion_id"])

    if op.get_bind().dialect.name == "postgresql":
        # Same protection as 0010: keep them out of Supabase's public REST API.
        for table in TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
