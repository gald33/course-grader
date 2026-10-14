"""Test students: enrollments.is_test flag.

A test student uses the site like any other student but is left out of
scores, normalisation, exports and grade sheets.

Revision ID: 0015_test_students
Revises: 0014_practice_rounds
Create Date: 2026-10-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_test_students"
down_revision: Union[str, None] = "0014_practice_rounds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("enrollments") as batch:
        batch.add_column(sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("enrollments") as batch:
        batch.drop_column("is_test")
