"""Course plans and private answer keys: lesson_answer_keys (each question's
key, kept out of the public repository and out of lesson versions),
course_plan_sessions (an imported course plan's sessions with each lesson's
readiness), and courses.instructor_email (private instructor contact, loaded
with the keys).

Additive only: two new tables and one nullable column; nothing existing is
altered or backfilled. Lesson versions installed before this keep any key
they embed. Downgrade drops the tables and the column, and every loaded
answer key and instructor contact with them (reload them from the private
file after upgrading again).

Revision ID: 0026_course_plan_answer_keys
Revises: 0025_custom_rubrics
Create Date: 2026-10-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026_course_plan_answer_keys"
down_revision: Union[str, None] = "0025_custom_rubrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("lesson_answer_keys", "course_plan_sessions")


def upgrade() -> None:
    op.create_table(
        "lesson_answer_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_slug", sa.String(length=64), nullable=False),
        sa.Column("question_key", sa.String(length=64), nullable=False),
        sa.Column("answer_json", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="upload"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("course_id", "lesson_slug", "question_key", name="uq_lesson_answer_key"),
    )
    op.create_index("ix_lesson_answer_keys_course_id", "lesson_answer_keys", ["course_id"])

    op.create_table(
        "course_plan_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_code", sa.String(length=64), nullable=False),
        sa.Column("session_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("lesson_slug", sa.String(length=64), nullable=False),
        sa.Column("fixture_key", sa.String(length=64), nullable=False),
        sa.Column("presentation_round", sa.Integer(), nullable=True),
        sa.Column("final_presentation_part", sa.Integer(), nullable=True),
        sa.Column("formal_presentations", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("planned_presenting_teams", sa.Integer(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("live_verified_at", sa.DateTime(), nullable=True),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("course_id", "session_number", name="uq_course_plan_session"),
    )
    op.create_index("ix_course_plan_sessions_course_id", "course_plan_sessions", ["course_id"])

    with op.batch_alter_table("courses") as batch:
        batch.add_column(sa.Column("instructor_email", sa.String(length=320), nullable=True))

    if op.get_bind().dialect.name == "postgresql":
        # Same protection as 0010: keep them out of Supabase's public REST API.
        for table in TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Destructive: drops every loaded answer key, the instructor contact and
    # the imported plan (lessons installed from it stay).
    with op.batch_alter_table("courses") as batch:
        batch.drop_column("instructor_email")
    op.drop_index("ix_course_plan_sessions_course_id", table_name="course_plan_sessions")
    op.drop_table("course_plan_sessions")
    op.drop_index("ix_lesson_answer_keys_course_id", table_name="lesson_answer_keys")
    op.drop_table("lesson_answer_keys")
