"""Add manual_grade column on submissions

Revision ID: 0003_manual_grade
Revises: 0002_missing_flags
Create Date: 2026-05-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_manual_grade"
down_revision: Union[str, None] = "0002_missing_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("submissions") as batch:
        batch.add_column(sa.Column("manual_grade", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("submissions") as batch:
        batch.drop_column("manual_grade")
