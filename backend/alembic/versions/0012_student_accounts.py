"""Student accounts: email (username) and invite/activation timestamps.

Revision ID: 0012_student_accounts
Revises: 0011_jobs_queue
Create Date: 2026-10-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_student_accounts"
down_revision: Union[str, None] = "0011_jobs_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("students") as batch:
        batch.add_column(sa.Column("email", sa.String(length=320), nullable=True))
        batch.add_column(sa.Column("invited_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("account_activated_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_students_email", ["email"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("students") as batch:
        batch.drop_index("ix_students_email")
        batch.drop_column("account_activated_at")
        batch.drop_column("invited_at")
        batch.drop_column("email")
