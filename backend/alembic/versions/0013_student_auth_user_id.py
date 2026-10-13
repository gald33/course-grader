"""Student accounts created by the instructor: keep the Supabase user id.

Revision ID: 0013_student_auth_user_id
Revises: 0012_student_accounts
Create Date: 2026-10-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_student_auth_user_id"
down_revision: Union[str, None] = "0012_student_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("students") as batch:
        batch.add_column(sa.Column("auth_user_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("students") as batch:
        batch.drop_column("auth_user_id")
