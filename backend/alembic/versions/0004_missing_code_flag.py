"""Add missing_code_flag on submissions

Revision ID: 0004_missing_code_flag
Revises: 0003_manual_grade
Create Date: 2026-05-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_missing_code_flag"
down_revision: Union[str, None] = "0003_manual_grade"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("submissions") as batch:
        batch.add_column(sa.Column("missing_code_flag", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("submissions") as batch:
        batch.drop_column("missing_code_flag")
