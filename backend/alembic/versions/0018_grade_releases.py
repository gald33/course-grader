"""Grade releases: which gradebook components students can see.

Revision ID: 0018_grade_releases
Revises: 0017_student_teams
Create Date: 2026-10-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_grade_releases"
down_revision: Union[str, None] = "0017_student_teams"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "grade_releases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("component", sa.String(length=32), nullable=False),
        sa.Column("released_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("course_id", "component", name="uq_grade_release_component"),
    )
    op.create_index("ix_grade_releases_course_id", "grade_releases", ["course_id"])
    if op.get_bind().dialect.name == "postgresql":
        # Same protection as 0010: keep it out of Supabase's public REST API.
        op.execute("ALTER TABLE grade_releases ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_grade_releases_course_id", table_name="grade_releases")
    op.drop_table("grade_releases")
