"""Alembic environment – online-migration mode using k7e_api Settings."""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Make k7e_api importable when alembic is invoked from apps/api/.
# apps/api/src is inserted at the front so it takes precedence over any
# installed editable copy that might have a different state.
# ---------------------------------------------------------------------------
_api_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _api_src not in sys.path:
    sys.path.insert(0, _api_src)

from k7e_api.config import get_settings  # noqa: E402 – must follow sys.path patch
from k7e_api.models import Base  # noqa: E402

# ---------------------------------------------------------------------------
# Alembic Config object – provides access to values in alembic.ini.
# ---------------------------------------------------------------------------
config = context.config

# Wire up the database URL from Settings so that the DATABASE_URL environment
# variable (or .env file) is always respected, overriding alembic.ini.
_settings = get_settings()
config.set_main_option("sqlalchemy.url", _settings.database_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata object for 'autogenerate' support.
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Migration runners
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection required).

    Useful for generating SQL scripts or running in CI without a database.
    """
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
    """Run migrations in 'online' mode (live DB connection)."""
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
