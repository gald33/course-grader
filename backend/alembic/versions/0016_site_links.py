"""Site links: rounds can require a working site link; link check results.

Revision ID: 0016_site_links
Revises: 0015_test_students
Create Date: 2026-10-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_site_links"
down_revision: Union[str, None] = "0015_test_students"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("review_rounds") as batch:
        batch.add_column(sa.Column("link_required", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("presentations") as batch:
        batch.add_column(sa.Column("link_status", sa.String(16), nullable=False, server_default=""))
        batch.add_column(sa.Column("link_detail", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("link_checked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("presentations") as batch:
        batch.drop_column("link_checked_at")
        batch.drop_column("link_detail")
        batch.drop_column("link_status")
    with op.batch_alter_table("review_rounds") as batch:
        batch.drop_column("link_required")
