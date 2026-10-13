from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.core.config import get_settings, sqlalchemy_database_url
from app.db.base import Base
from app.models import *  # noqa: F403,F401

config = context.config
settings = get_settings()
# "%" is ConfigParser interpolation syntax; URL-encoded passwords contain it.
config.set_main_option("sqlalchemy.url", sqlalchemy_database_url(settings.database_url).replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Alembic makes version_num VARCHAR(32), but revision
        # 0008_rename_initial_stage_to_presentation is 42 characters. SQLite
        # ignores the limit; Postgres enforces it. Create the table wider up
        # front (a no-op where it already exists).
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(64) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
        if connection.dialect.name == "postgresql":
            connection.execute(text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)"))
        connection.commit()

        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
