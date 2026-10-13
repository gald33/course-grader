from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings, sqlalchemy_database_url

settings = get_settings()
database_url = sqlalchemy_database_url(settings.database_url)

engine_kwargs: dict = {"future": True}
if database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_pre_ping"] = True
    # Supabase's transaction pooler can't keep server-side prepared statements.
    engine_kwargs["connect_args"] = {"prepare_threshold": None}
    if settings.database_null_pool:
        engine_kwargs["poolclass"] = NullPool

engine = create_engine(database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
