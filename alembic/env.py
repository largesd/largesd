"""
Alembic environment for Blind Debate Adjudicator.

Supports both SQLite and PostgreSQL via DATABASE_URL.
Autogenerate is disabled because the project uses raw SQL, not SQLAlchemy ORM.
"""
import os
from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No SQLAlchemy models -> no autogenerate support
target_metadata = None


def get_database_url() -> str:
    """Read DATABASE_URL from env, with sensible fallback."""
    url = os.getenv("DATABASE_URL", "")
    if url:
        return url
    # Fallback to SQLite default used by the app
    return "sqlite:///data/debate_system.db"


def run_migrations_offline() -> None:
    """Run migrations in offline mode (generates SQL script)."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode (applies to live DB)."""
    url = get_database_url()
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
