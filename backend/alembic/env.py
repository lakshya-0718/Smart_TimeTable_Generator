"""
Alembic configuration — env.py

This file wires Alembic to our SQLAlchemy models and database URL.
It supports both online (connected to DB) and offline (SQL-script) modes.

Import order:
  1. app.core.database — provides Base (DeclarativeBase)
  2. app.models        — the package __init__.py registers every model
                         class on Base.metadata in the correct FK-safe order.
     Importing the package is sufficient; no individual model imports needed.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings

# ── Register all ORM models on Base.metadata ─────────────────────────
# Importing app.models causes its __init__.py to execute, which imports
# every model class in FK-safe order. After this line, Base.metadata
# contains the full table graph that autogenerate will diff against.
from app.core.database import Base
import app.models  # noqa: F401  — side-effect import: registers all models

# Alembic Config object
config = context.config

# Override sqlalchemy.url with the value from our Pydantic settings.
# This ensures env.py and the application code always use the same DB URL.
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL_SYNC)

# Logging — reads [loggers] / [handlers] / [formatters] from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object that Alembic's autogenerate will diff
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    Offline mode generates a SQL script without an active DB connection.
    Useful for review, DBA approval, or environments without direct DB access.
    Run with: alembic upgrade --sql head
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Render AS ENUM so that enum types are created via CREATE TYPE,
        # not as VARCHAR with a CHECK constraint.
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    Online mode connects directly to the database and applies migrations.
    Run with: alembic upgrade head
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
