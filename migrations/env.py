"""Alembic configuration for async migrations."""

import os
import sys
from pathlib import Path
from logging.config import fileConfig

from alembic import context

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import settings  # noqa: E402
from database import Base, engine  # noqa: E402

# Alembic Configuration
config = context.config

# Initialize logger
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = settings.database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


import asyncio


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    from sqlalchemy.ext.asyncio import async_engine_from_config

    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = settings.database_url
    
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=None,
    )

    async def run_migrations():
        async with connectable.connect() as connection:
            await connection.run_sync(
                lambda conn: context.configure(
                    connection=conn,
                    target_metadata=target_metadata,
                    render_as_batch=True,
                )
            )
            await connection.run_sync(
                lambda conn: context.run_migrations()
            )

    asyncio.run(run_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
