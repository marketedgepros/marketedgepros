"""
Flask-Migrate environment configuration
"""
from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy.engine import make_url
from migrations.target_safety import validate_isolated_postgresql_target
from sqlalchemy import pool
from alembic import context
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.database import db
from src.models import *  # Import all models

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata
target_metadata = db.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    _validate_testing_target(url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_migrations_with_connection(connection) -> None:
    """Run one online migration operation on a caller-owned connection."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def _validate_testing_target(database_url: str, connection=None) -> None:
    """Fail closed when an isolated test invocation lacks its declared target."""
    if os.environ.get("FLASK_TESTING", "").lower() != "true":
        return
    if not database_url:
        raise RuntimeError("Testing Alembic execution requires an explicit database URL")
    declared = make_url(database_url)
    if connection is not None:
        if declared != connection.engine.url:
            raise RuntimeError("Supplied Alembic connection differs from declared testing URL")
    else:
        expected = os.environ.get("TEST_DATABASE_URL")
        if not expected or declared != make_url(expected):
            raise RuntimeError("Testing Alembic URL must equal TEST_DATABASE_URL without a supplied connection")
    validate_isolated_postgresql_target(database_url)


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    supplied_connection = config.attributes.get("connection")
    configured_url = config.get_main_option("sqlalchemy.url")
    if supplied_connection is not None:
        _validate_testing_target(configured_url, supplied_connection)
        _run_migrations_with_connection(supplied_connection)
        return

    if configured_url:
        _validate_testing_target(configured_url)
        configuration = config.get_section(config.config_ini_section)
        configuration['sqlalchemy.url'] = configured_url
        connectable = engine_from_config(
            configuration,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with connectable.connect() as connection:
            _run_migrations_with_connection(connection)
        return

    # Preserve the application-owned deployment path only outside isolated tests.
    if os.environ.get("FLASK_TESTING", "").lower() == "true":
        raise RuntimeError("Testing Alembic execution requires an explicit synthetic target")
    from src.config import get_config
    config_obj = get_config()
    configuration = config.get_section(config.config_ini_section)
    configuration['sqlalchemy.url'] = config_obj.SQLALCHEMY_DATABASE_URI
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _run_migrations_with_connection(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
