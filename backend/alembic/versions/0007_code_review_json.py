"""Add code_review_json column on submissions

Stores per-dimension auto-generated explanations (deterministic + LLM) for the
hw2_code / project_code rubric, mirroring how project_llm_review_json holds
report-rubric rationales.

Revision ID: 0007_code_review_json
Revises: 0006_rubric_approved
Create Date: 2026-05-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_code_review_json"
down_revision: Union[str, None] = "0006_rubric_approved"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("submissions") as batch:
        batch.add_column(sa.Column("code_review_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("submissions") as batch:
        batch.drop_column("code_review_json")
