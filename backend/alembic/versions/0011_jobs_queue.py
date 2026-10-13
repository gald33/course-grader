"""Database-backed job queue (replaces Celery + Redis).

Revision ID: 0011_jobs_queue
Revises: 0010_lock_down_supabase_api
Create Date: 2026-10-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_jobs_queue"
down_revision: Union[str, None] = "0010_lock_down_supabase_api"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("args_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("worker", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_jobs_status_id", "jobs", ["status", "id"])
    if op.get_bind().dialect.name == "postgresql":
        # Same protection as 0010: keep it out of Supabase's public REST API.
        op.execute("ALTER TABLE jobs ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_jobs_status_id", table_name="jobs")
    op.drop_table("jobs")
