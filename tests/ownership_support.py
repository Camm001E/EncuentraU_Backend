import os
import secrets
from dataclasses import dataclass, field
from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import Settings, get_settings
from app.domain.matching import MatchableObject, MatchRequest
from app.infrastructure.auth_security import JWTAccessTokenService
from app.infrastructure.database import session as database_session
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import create_database_engine
from app.infrastructure.database.models import ObjectMatch, ObjectReport, User
from app.infrastructure.database.user_repository import SQLAlchemyUserRepository


@dataclass
class WorkflowContext:
    client: TestClient
    engine: object
    settings: Settings
    ids: dict[str, UUID]
    headers: dict[str, dict[str, str]] = field(repr=False)
    match_id: UUID
    lost_id: UUID
    found_id: UUID

    def claim(self, evidence="Respuesta privada suficientemente detallada", actor="A"):
        return self.client.post(
            f"/api/v1/matches/{self.match_id}/claims",
            json={"ownership_evidence": evidence},
            headers=self.headers[actor],
        )

    def approve(self, claim_id):
        return self.client.post(
            f"/api/v1/admin/claims/{claim_id}/approve", headers=self.headers["admin"]
        )

    def approved(self):
        response = self.claim()
        assert response.status_code == 201
        approved = self.approve(response.json()["id"])
        assert approved.status_code == 200
        return response.json()["id"], approved.json()["conversation_id"]


@pytest.fixture(
    params=["sqlite", pytest.param("postgresql", marks=pytest.mark.postgresql)]
)
def workflow(request, monkeypatch, tmp_path):
    control, schema = None, None
    if request.param == "postgresql":
        raw = os.environ.get("TEST_DATABASE_URL")
        if not raw:
            pytest.skip("TEST_DATABASE_URL aislada requerida.")
        if "_test" not in (make_url(raw).database or ""):
            pytest.fail("La base de pruebas debe contener _test en su nombre.")
        control = create_database_engine(SecretStr(raw))
        schema = "claims_test_" + uuid4().hex
        with control.begin() as connection:
            connection.execute(CreateSchema(schema))
        engine = create_engine(
            raw,
            hide_parameters=True,
            connect_args={"options": "-csearch_path=" + schema},
        )
        with engine.begin() as connection:
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    else:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            hide_parameters=True,
        )

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database_session, "get_session_factory", lambda: factory)
    settings = Settings(
        _env_file=None,
        database_url=None,
        jwt_secret_key=secrets.token_hex(32),
        report_image_storage_path=tmp_path,
    )
    from app.application.matching_service import MatchingService
    from app.main import create_app

    with factory() as session:
        names = {
            "A": "Alice ApellidoPrivado",
            "B": "Bruno OtroApellido",
            "C": "Clara Tercera",
            "admin": "Diana Administradora",
            "inactive": "Cuenta Inactiva",
        }
        users = {
            key: User(
                id=uuid4(),
                full_name=name,
                email=key.lower() + "@example.com",
                student_code=key.upper(),
                password_hash="not-a-usable-password-hash",
                role="admin" if key in ("admin", "inactive") else "student",
                is_active=key != "inactive",
            )
            for key, name in names.items()
        }
        session.add_all(users.values())
        session.flush()
        attrs = dict(
            object_type="audífonos de diadema",
            category="electronica",
            primary_color="negro",
            secondary_colors=["azul"],
            shape="diadema acolchada",
            brand=None,
            description="Audífonos negros con detalles azules.",
            location="Cafetería central",
            event_date=date.today() - timedelta(days=1),
        )
        lost = ObjectReport(
            id=uuid4(),
            user_id=users["A"].id,
            report_type="lost",
            private_feature="Detalle privado perdido",
            **attrs,
        )
        found = ObjectReport(
            id=uuid4(),
            user_id=users["B"].id,
            report_type="found",
            private_feature="Detalle privado encontrado",
            **attrs,
        )
        session.add_all([lost, found])
        session.flush()
        obj = MatchableObject(**attrs)
        evaluation = MatchingService().evaluate(MatchRequest(lost=obj, found=obj))
        match = ObjectMatch(
            id=uuid4(),
            lost_report_id=lost.id,
            found_report_id=found.id,
            **evaluation.model_dump(mode="json"),
        )
        session.add(match)
        session.commit()
        ids = {key: value.id for key, value in users.items()}
        tokens = JWTAccessTokenService(settings)
        repository = SQLAlchemyUserRepository(session)
        headers = {
            key: {
                "Authorization": "Bearer "
                + tokens.issue(repository.get_by_id(value)).value
            }
            for key, value in ids.items()
        }
        match_id, lost_id, found_id = match.id, lost.id, found.id
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            yield WorkflowContext(
                client, engine, settings, ids, headers, match_id, lost_id, found_id
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        if control is not None:
            with control.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
            control.dispose()
