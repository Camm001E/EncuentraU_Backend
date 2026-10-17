from logging.config import fileConfig

from alembic import context
from alembic.util import CommandError
from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.infrastructure.database import models  # noqa: F401
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import (
    DatabaseConfigurationError,
    get_engine,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def migrate_connection(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations() -> None:
    if context.is_offline_mode():
        url = config.attributes.get("database_url")
        if url is None:
            url = get_engine().url
        context.configure(
            url=url,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    connection = config.attributes.get("connection")
    if connection is not None:
        migrate_connection(connection)
        return
    engine = get_engine()
    try:
        with engine.connect() as connection:
            migrate_connection(connection)
    finally:
        engine.dispose()


try:
    run_migrations()
except (DatabaseConfigurationError, SQLAlchemyError):
    raise CommandError(
        "No se pudo completar la migración. "
        "Revisa la configuración y disponibilidad de PostgreSQL."
    ) from None
