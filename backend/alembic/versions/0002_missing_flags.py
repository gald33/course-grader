"""Add manual missing-report / missing-data flags to submissions

Revision ID: 0002_missing_flags
Revises: 0001_initial
Create Date: 2026-05-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_missing_flags"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("submissions") as batch:
        batch.add_column(sa.Column("missing_report_flag", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("missing_data_flag", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("submissions") as batch:
        batch.drop_column("missing_data_flag")
        batch.drop_column("missing_report_flag")
