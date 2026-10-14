"""Practice review rounds: counts_toward_grade flag.

Revision ID: 0014_practice_rounds
Revises: 0013_student_auth_user_id
Create Date: 2026-10-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_practice_rounds"
down_revision: Union[str, None] = "0013_student_auth_user_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("review_rounds") as batch:
        batch.add_column(sa.Column("counts_toward_grade", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("review_rounds") as batch:
        batch.drop_column("counts_toward_grade")
