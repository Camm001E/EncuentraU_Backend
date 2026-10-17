from functools import lru_cache

from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from app.core.config import get_settings


class DatabaseConfigurationError(RuntimeError):
    """Controlled error that never includes the connection string."""


def create_database_engine(database_url: SecretStr | None) -> Engine:
    if database_url is None:
        raise DatabaseConfigurationError("La base de datos no está configurada.")
    try:
        url = make_url(database_url.get_secret_value())
        if url.drivername not in {"postgresql", "postgresql+psycopg"}:
            raise DatabaseConfigurationError("Se requiere PostgreSQL con psycopg 3.")
        return create_engine(
            url.set(drivername="postgresql+psycopg"),
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False,
            hide_parameters=True,
            connect_args={"connect_timeout": 5, "application_name": "encuentrau"},
        )
    except (ArgumentError, ValueError):
        raise DatabaseConfigurationError(
            "La configuración de PostgreSQL no es válida."
        ) from None


@lru_cache
def get_engine() -> Engine:
    """Create the pool lazily; importing the application never opens a connection."""
    return create_database_engine(get_settings().database_url)


def check_database_connection() -> bool:
    try:
        with get_engine().connect() as connection:
            return connection.execute(text("SELECT 1")).scalar_one() == 1
    except (DatabaseConfigurationError, SQLAlchemyError):
        return False
