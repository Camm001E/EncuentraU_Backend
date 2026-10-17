from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect


def migration_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


def test_initial_migration_is_importable() -> None:
    script = ScriptDirectory.from_config(migration_config())
    assert script.get_heads() == ["0001_postgresql_foundation"]
    revision = script.get_revision("head")
    assert revision.down_revision is None
    assert callable(revision.module.upgrade)
    assert callable(revision.module.downgrade)


def test_migration_generates_postgresql_sql_without_credentials() -> None:
    config = migration_config()
    config.attributes["database_url"] = "postgresql+psycopg://localhost/example"
    config.output_buffer = StringIO()
    command.upgrade(config, "head", sql=True)
    sql = config.output_buffer.getvalue()
    for table in ("users", "object_reports", "image_analyses", "object_matches"):
        assert f"CREATE TABLE {table}" in sql
    assert "JSONB" in sql
    assert "uq_object_matches_pair" in sql
    assert "postgresql+psycopg://" not in sql


def test_migration_can_upgrade_downgrade_and_upgrade_again() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    config = migration_config()
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            assert len(inspect(connection).get_table_names()) == 5
            command.downgrade(config, "base")
            assert inspect(connection).get_table_names() == ["alembic_version"]
            command.upgrade(config, "head")
            assert len(inspect(connection).get_table_names()) == 5
    finally:
        engine.dispose()
