"""Generate Alembic revision file."""

from alembic import context
from database import Base

# this is the Alembic Config object
config = context.config

# Import your Model to generate your迁移 scripts
from models import users, chats, files, providers, config  # noqa: F401

target_metadata = Base.metadata

def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode."""
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(config.get_main_option("sqlalchemy.url"))
    
    connectable = engine
    
    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
