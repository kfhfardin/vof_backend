"""Alembic env — multi-DB aware.

Invoked via `scripts/alembic_wrapper.py {app|brain} ...` which sets
ALEMBIC_DB={app|brain} before calling alembic, so we know which database
URL + which Base.metadata to use.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.db.models  # noqa: F401  # register models on Base.metadata
from app.db.base import Base, BrainBase
from app.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_TARGET = os.environ.get("ALEMBIC_DB", "app")
settings = get_settings()

if _TARGET == "app":
    target_metadata = Base.metadata
    sqlalchemy_url = settings.database_url.replace("+asyncpg", "+psycopg")
elif _TARGET == "brain":
    target_metadata = BrainBase.metadata
    sqlalchemy_url = settings.brain_database_url.replace("+asyncpg", "+psycopg")
else:
    raise RuntimeError(f"ALEMBIC_DB must be 'app' or 'brain', got {_TARGET!r}")

config.set_main_option("sqlalchemy.url", sqlalchemy_url)
# version_locations is set in the per-target alembic.ini (alembic.ini for
# the app DB, alembic-brain.ini for the brain DB), not here - it has to
# land before ScriptDirectory is constructed, which is before env.py runs.


def run_migrations_offline() -> None:
    context.configure(
        url=sqlalchemy_url,
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
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
