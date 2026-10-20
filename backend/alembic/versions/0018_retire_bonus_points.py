"""Retire enrollments.bonus_points in favour of `bonus` component overrides.

Existing non-zero values become one override each, so every bonus now lives
in student_component_overrides and the gradebook total is unchanged.

Revision ID: 0018_retire_bonus_points
Revises: 0017_student_teams
Create Date: 2026-10-20
"""

from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_retire_bonus_points"
down_revision: Union[str, None] = "0017_student_teams"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MIGRATED_REASON = "Project bonus (migrated from enrollment bonus_points)"


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT course_id, student_id, bonus_points FROM enrollments WHERE bonus_points IS NOT NULL AND bonus_points <> 0")
    ).fetchall()
    now = datetime.utcnow()
    for course_id, student_id, bonus in rows:
        conn.execute(
            sa.text(
                "INSERT INTO student_component_overrides (course_id, student_id, submission_id, component, delta, reason, created_at) "
                "VALUES (:c, :s, NULL, 'bonus', :d, :r, :t)"
            ),
            {"c": course_id, "s": student_id, "d": float(bonus), "r": MIGRATED_REASON, "t": now},
        )
    with op.batch_alter_table("enrollments") as batch:
        batch.drop_column("bonus_points")


def downgrade() -> None:
    with op.batch_alter_table("enrollments") as batch:
        batch.add_column(sa.Column("bonus_points", sa.Float(), nullable=False, server_default="0"))
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE enrollments SET bonus_points = ("
            "SELECT COALESCE(SUM(o.delta), 0) FROM student_component_overrides o "
            "WHERE o.course_id = enrollments.course_id AND o.student_id = enrollments.student_id "
            "AND o.component = 'bonus' AND o.reason = :r)"
        ),
        {"r": MIGRATED_REASON},
    )
    conn.execute(
        sa.text("DELETE FROM student_component_overrides WHERE component = 'bonus' AND reason = :r"),
        {"r": MIGRATED_REASON},
    )
