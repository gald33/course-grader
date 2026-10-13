"""Add approved flag on rubric_dimension_scores

Revision ID: 0006_rubric_approved
Revises: 0005_llm_review
Create Date: 2026-05-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_rubric_approved"
down_revision: Union[str, None] = "0005_llm_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("rubric_dimension_scores") as batch:
        # Default existing rows to approved=True — anything already in the table
        # was set manually before LLM auto-apply existed.
        batch.add_column(
            sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("rubric_dimension_scores") as batch:
        batch.drop_column("approved")
