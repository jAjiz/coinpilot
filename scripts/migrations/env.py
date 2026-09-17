"""Alembic environment.

The URL arrives from the process environment through `core.config`, so the migrations and
the application agree on where the database is without a connection string living in a
committed file.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from core.config import database_url
from core.db.models import Base

config = context.config

# A caller may set the URL itself, and the test fixture does. Only fall back to the
# environment when nothing set one. The doubled percent signs escape configparser, which
# would otherwise read a percent in a password as an interpolation.
if not config.get_main_option("sqlalchemy.url", ""):
    config.set_main_option("sqlalchemy.url", database_url().replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
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
