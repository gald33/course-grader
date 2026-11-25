"""Peer rounds: the AI grader's share of each team score (review_rounds.llm_weight).

Before this, the AI grader was one more reviewer, about 1/36 of a team score in
a class of 40. Now a team score is (1 - llm_weight) x the class's view +
llm_weight x the AI's view, default 1/3.

Additive only: one column with a server default, so existing rounds get 1/3.
Rounds without an AI review score exactly as before.

Revision ID: 0028_peer_round_llm_weight
Revises: 0027_feedback_tickets
Create Date: 2026-11-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_peer_round_llm_weight"
down_revision: Union[str, None] = "0027_feedback_tickets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("review_rounds") as batch:
        batch.add_column(sa.Column("llm_weight", sa.Float(), nullable=False, server_default=sa.text(repr(1 / 3))))


def downgrade() -> None:
    with op.batch_alter_table("review_rounds") as batch:
        batch.drop_column("llm_weight")
