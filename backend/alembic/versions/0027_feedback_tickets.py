"""Feedback tickets: feedback_tickets and feedback_ticket_notes, org-core's
tickets-core record (SPEC §17) in this app's database. Every page's Feedback
button files a ticket here; org-core's roles read and annotate them through
/api/admin/feedback with the ORG_TICKETS_TOKEN service token.

Additive only: two new tables; nothing existing is altered. Downgrade drops
both, and every ticket and note with them.

Revision ID: 0027_feedback_tickets
Revises: 0026_course_plan_answer_keys
Create Date: 2026-11-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_feedback_tickets"
down_revision: Union[str, None] = "0026_course_plan_answer_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("feedback_tickets", "feedback_ticket_notes")


def upgrade() -> None:
    op.create_table(
        "feedback_tickets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("reporter_ref", sa.String(length=64), nullable=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("feedback_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("kinds_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("refs_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("deployed_version_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_feedback_tickets_course_id", "feedback_tickets", ["course_id"])
    op.create_index("ix_feedback_tickets_status", "feedback_tickets", ["status"])
    op.create_index("ix_feedback_tickets_created_at", "feedback_tickets", ["created_at"])

    op.create_table(
        "feedback_ticket_notes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "ticket_id", sa.String(length=36), sa.ForeignKey("feedback_tickets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("author", sa.String(length=128), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("meta_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_feedback_ticket_notes_ticket", "feedback_ticket_notes", ["ticket_id", "created_at"])

    if op.get_bind().dialect.name == "postgresql":
        # Same protection as 0010: keep them out of Supabase's public REST API.
        for table in TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Destructive: drops every ticket and note.
    op.drop_index("ix_feedback_ticket_notes_ticket", table_name="feedback_ticket_notes")
    op.drop_table("feedback_ticket_notes")
    op.drop_index("ix_feedback_tickets_created_at", table_name="feedback_tickets")
    op.drop_index("ix_feedback_tickets_status", table_name="feedback_tickets")
    op.drop_index("ix_feedback_tickets_course_id", table_name="feedback_tickets")
    op.drop_table("feedback_tickets")
