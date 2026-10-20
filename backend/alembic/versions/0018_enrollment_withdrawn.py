"""Withdrawn students: kept on the roster for history, out of everything else.

Revision ID: 0018_enrollment_withdrawn
Revises: 0017_student_teams
Create Date: 2026-10-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_enrollment_withdrawn"
down_revision: Union[str, None] = "0017_student_teams"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("enrollments") as batch:
        batch.add_column(sa.Column("withdrawn_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("enrollments") as batch:
        batch.drop_column("withdrawn_at")
