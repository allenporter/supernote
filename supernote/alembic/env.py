import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection, engine_from_config
from sqlalchemy.ext.asyncio import async_engine_from_config

# Add the project root to sys.path so we can import supernote modules
sys.path.append(str(Path(__file__).parent.parent))

from supernote.server.config import ServerConfig
from supernote.server.db.base import Base

# Import all models so they are registered with Base.metadata
from supernote.server.db.models import *  # noqa

# ----------------------------------------------------------------------

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None and not config.get_main_option(
    "skip_logging_config"
):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# target_metadata is the MetaData object of your ORM base
target_metadata = Base.metadata

# Override sqlalchemy.url with the one from our application config
# We load the config without a file (defaults) or from env vars
# BUT we only do this if the config hasn't been set explicitly (e.g. by a test)
current_url = config.get_main_option("sqlalchemy.url")
if not current_url or "driver://" in current_url:
    app_config = ServerConfig.load()
    config.set_main_option("sqlalchemy.url", app_config.db_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

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


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    # Check if we are using an async driver
    url = config.get_main_option("sqlalchemy.url")
    assert url is not None
    is_async = url.startswith("sqlite+aiosqlite") or url.startswith(
        "postgresql+asyncpg"
    )

    if is_async:
        asyncio.run(run_async_migrations())
    else:
        # Standard sync migration
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        with connectable.connect() as connection:
            do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
