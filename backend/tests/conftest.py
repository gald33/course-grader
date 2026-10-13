import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def db_engine(tmp_path):
    """Fresh database per test: SQLite by default, or the Postgres database in
    TEST_DATABASE_URL (its public schema is wiped)."""
    import app.models  # noqa: F401  (registers every table on Base.metadata)
    from app.core.config import sqlalchemy_database_url
    from app.db.base import Base

    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        engine = create_engine(sqlalchemy_database_url(url), connect_args={"prepare_threshold": None})
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
