"""Add project_llm_review_json column on submissions

Revision ID: 0005_llm_review
Revises: 0004_missing_code_flag
Create Date: 2026-05-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_llm_review"
down_revision: Union[str, None] = "0004_missing_code_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("submissions") as batch:
        batch.add_column(sa.Column("project_llm_review_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("submissions") as batch:
        batch.drop_column("project_llm_review_json")
