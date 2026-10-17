import os
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.infrastructure.database import engine as database_engine
from app.infrastructure.database.models import ImageAnalysis
from app.main import app
from tests.test_database_models import make_match, make_report, make_user
from tests.test_migrations import migration_config


@pytest.mark.postgresql
def test_postgresql_migrations_constraints_json_and_health(monkeypatch) -> None:
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip(
            "TEST_DATABASE_URL no está definida; no se conecta a una base real."
        )
    engine = database_engine.create_database_engine(SecretStr(raw_url))
    schema = "encuentrau_test_" + uuid4().hex
    try:
        with engine.connect() as connection:
            connection.execute(CreateSchema(schema))
            connection.commit()
            try:
                connection.exec_driver_sql(f'SET search_path TO "{schema}"')
                connection.commit()
                config = migration_config()
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                inspector = inspect(connection)
                assert set(inspector.get_table_names()) == {
                    "users",
                    "object_reports",
                    "image_analyses",
                    "object_matches",
                    "alembic_version",
                }
                columns = {
                    column["name"]: column
                    for column in inspector.get_columns("image_analyses")
                }
                assert isinstance(columns["extracted_data"]["type"], JSONB)
                connection.commit()

                with Session(connection, expire_on_commit=False) as session:
                    user = make_user()
                    session.add(user)
                    session.flush()
                    lost = make_report(user.id)
                    found = make_report(user.id, "found")
                    session.add_all([lost, found])
                    session.flush()
                    session.add_all(
                        [
                            make_match(lost.id, found.id),
                            ImageAnalysis(
                                report_id=found.id,
                                provider="example",
                                model="example",
                                extracted_data={"object_detected": True},
                                confidence="alta",
                            ),
                        ]
                    )
                    session.commit()
                    assert user.created_at.tzinfo is not None
                    assert session.scalar(select(ImageAnalysis.extracted_data)) == {
                        "object_detected": True
                    }

                for invalid in (
                    make_user(email=user.email),
                    make_match(lost.id, found.id),
                    make_match(found.id, lost.id, identity_percentage=Decimal("101")),
                    make_report(uuid4()),
                ):
                    with Session(connection) as session:
                        session.add(invalid)
                        with pytest.raises(IntegrityError):
                            session.flush()
                        session.rollback()

                command.check(config)
                command.downgrade(config, "base")
                assert inspect(connection).get_table_names() == ["alembic_version"]
                connection.commit()
                command.upgrade(config, "head")
                assert connection.scalar(text("SELECT count(*) FROM users")) == 0
                connection.commit()

                monkeypatch.setattr(database_engine, "get_engine", lambda: engine)
                with TestClient(app) as client:
                    response = client.get("/health/database")
                assert response.status_code == 200
                assert response.json()["database"] == "postgresql"
            finally:
                connection.rollback()
                connection.exec_driver_sql("SET search_path TO public")
                connection.execute(DropSchema(schema, cascade=True))
                connection.commit()
    finally:
        engine.dispose()
