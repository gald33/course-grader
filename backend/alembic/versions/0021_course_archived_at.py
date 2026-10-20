"""Courses can be archived (hidden from the home page, restorable).

Revision ID: 0021_course_archived_at
Revises: 0020_enrollment_withdrawn
Create Date: 2026-10-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_course_archived_at"
down_revision: Union[str, None] = "0020_enrollment_withdrawn"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("courses") as batch:
        batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("courses") as batch:
        batch.drop_column("archived_at")
