"""Retire enrollments.bonus_points, phase 1: the project bonus moves to
`bonus` component overrides.

Existing non-zero values become one tagged override each and the column is
zeroed, so every bonus lives in student_component_overrides and totals are
unchanged. The column itself stays (NOT NULL, now with a server default of 0)
so this can be applied while the previous code is still serving: that code
reads bonus_points + bonus overrides = 0 + override, the same total, and
inserts an explicit 0. Phase 2 (a later migration) drops the column.

Revision ID: 0020_retire_bonus_points
Revises: 0019_teams_deadline
Create Date: 2026-10-20
"""

from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_retire_bonus_points"
down_revision: Union[str, None] = "0019_teams_deadline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MIGRATED_REASON = "Project bonus (migrated from enrollment bonus_points)"


def upgrade() -> None:
    # Default first: on Postgres this takes the table lock up front, so old-code
    # writes to bonus_points wait until the copy below has committed.
    with op.batch_alter_table("enrollments") as batch:
        batch.alter_column("bonus_points", existing_type=sa.Float(), existing_nullable=False, server_default=sa.text("0"))
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT course_id, student_id, bonus_points FROM enrollments WHERE bonus_points <> 0")
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
    conn.execute(sa.text("UPDATE enrollments SET bonus_points = 0 WHERE bonus_points <> 0"))


def downgrade() -> None:
    # Only the overrides this migration created (tagged with MIGRATED_REASON)
    # move back into the column; `bonus` overrides added later stay overrides.
    # The old code sums column + overrides, so totals are unchanged either way.
    # `+` (not `=`) keeps anything old code wrote to the column in the meantime.
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE enrollments SET bonus_points = bonus_points + ("
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
    with op.batch_alter_table("enrollments") as batch:
        batch.alter_column("bonus_points", existing_type=sa.Float(), existing_nullable=False, server_default=None)
