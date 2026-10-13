"""Keep app tables out of Supabase's auto-generated REST API.

Supabase exposes the public schema over its HTTP API to the `anon` and
`authenticated` roles, and the anon (publishable) key is meant to be public.
The app only connects as the database owner, so on Postgres: enable row level
security with no policies on every table, and revoke the API roles' access to
current and future tables. The owner bypasses RLS, so the app is unaffected.
No-op on SQLite, and the role statements are skipped where the roles don't
exist (plain Postgres).

Revision ID: 0010_lock_down_supabase_api
Revises: 0009_peer_review
Create Date: 2026-10-13
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0010_lock_down_supabase_api"
down_revision: Union[str, None] = "0009_peer_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_DOWN = """
DO $$
DECLARE
    t record;
    api_role text;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
    END LOOP;
    FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', api_role);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', api_role);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %I', api_role);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I', api_role);
        END IF;
    END LOOP;
END $$;
"""


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(LOCK_DOWN)


def downgrade() -> None:
    # Re-exposing student data through the public API is never wanted.
    pass
