"""Students form teams: join codes on teams; per-course team settings.

Revision ID: 0017_student_teams
Revises: 0016_site_links
Create Date: 2026-10-14
"""

import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_student_teams"
down_revision: Union[str, None] = "0016_site_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def upgrade() -> None:
    with op.batch_alter_table("courses") as batch:
        batch.add_column(sa.Column("teams_open", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("max_team_size", sa.Integer(), nullable=False, server_default="7"))
    with op.batch_alter_table("teams") as batch:
        batch.add_column(sa.Column("join_code", sa.String(16), nullable=True))
    conn = op.get_bind()
    used: set[str] = set()
    for (team_id,) in conn.execute(sa.text("SELECT id FROM teams")).fetchall():
        code = "".join(secrets.choice(ALPHABET) for _ in range(6))
        while code in used:
            code = "".join(secrets.choice(ALPHABET) for _ in range(6))
        used.add(code)
        conn.execute(sa.text("UPDATE teams SET join_code = :c WHERE id = :i"), {"c": code, "i": team_id})
    op.create_index("ix_teams_join_code", "teams", ["join_code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_teams_join_code", table_name="teams")
    with op.batch_alter_table("teams") as batch:
        batch.drop_column("join_code")
    with op.batch_alter_table("courses") as batch:
        batch.drop_column("max_team_size")
        batch.drop_column("teams_open")
