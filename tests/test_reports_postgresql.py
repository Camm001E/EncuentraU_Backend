import os
import secrets
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import Settings, get_settings
from app.domain.object_reports import (
    ReportAttributes,
    ReportConflictError,
    ReportNotActiveError,
)
from app.infrastructure.auth_security import JWTAccessTokenService
from app.infrastructure.database import session as database_session
from app.infrastructure.database.engine import create_database_engine
from app.infrastructure.database.models import ImageAnalysis, ObjectReport, User
from app.infrastructure.database.object_report_repository import (
    SQLAlchemyObjectReportRepository,
)
from app.infrastructure.database.user_repository import SQLAlchemyUserRepository
from app.main import create_app
from tests.test_migrations import migration_config

pytestmark = pytest.mark.postgresql
REPORTS = "/api/v1/reports"


def payload(**changes):
    return {
        "report_type": "lost",
        "object_type": " Audífonos  Bluetooth ",
        "category": " Electronica ",
        "primary_color": " NEGRO ",
        "secondary_colors": ["Azul", "azul", "Negro"],
        "brand": " JBL ",
        "shape": "Estuche ovalado",
        "description": "Audífonos con estuche compacto.",
        "location": "Cafetería central",
        "event_date": date.today().isoformat(),
        "private_feature": "Detalle que solo conoce el propietario",
        **changes,
    }


def analysis():
    return {
        "extracted_data": {
            "object_detected": True,
            "object_type": "Audífonos Bluetooth",
            "visible_features": ["Estuche ovalado", "Detalle azul"],
            "image_quality": "buena",
            "confidence": "alta",
        },
        "confidence": "alta",
    }


@pytest.fixture(scope="module")
def reports_engine():
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Se requiere TEST_DATABASE_URL en una base PostgreSQL aislada.")
    url = make_url(raw)
    if "_test" not in (url.database or ""):
        pytest.fail("La base de integración debe tener _test en su nombre.")
    engine = create_database_engine(SecretStr(raw))
    try:
        yield engine
    finally:
        engine.dispose()


@dataclass
class ReportContext:
    client: TestClient
    connection: object
    engine: Engine
    settings: Settings
    user_id: UUID
    other_user_id: UUID
    headers: dict[str, str] = field(repr=False)
    other_headers: dict[str, str] = field(repr=False)
    sessions: list[Session]


@pytest.fixture
def reports(reports_engine, monkeypatch):
    schema = "report_test_" + uuid4().hex
    with reports_engine.connect() as connection:
        connection.execute(CreateSchema(schema))
        connection.commit()
        try:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            config = migration_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.commit()
            settings = Settings(
                _env_file=None,
                database_url=None,
                jwt_secret_key=secrets.token_hex(32),
                gemini_model="gemini-test-model",
            )
            with Session(connection) as session:
                owner = User(
                    full_name="Report Owner",
                    email="owner@example.com",
                    student_code="OWNER",
                    password_hash="test-only-not-used-for-login",
                )
                other = User(
                    full_name="Other Owner",
                    email="other@example.com",
                    student_code="OTHER",
                    password_hash="test-only-not-used-for-login",
                )
                session.add_all([owner, other])
                session.flush()
                owner_id, other_id = owner.id, other.id
                session.commit()
            with Session(connection) as session:
                users = SQLAlchemyUserRepository(session)
                tokens = JWTAccessTokenService(settings)
                owner_token = tokens.issue(users.get_by_id(owner_id)).value
                other_token = tokens.issue(users.get_by_id(other_id)).value
            closed = []

            class TrackedSession(Session):
                def close(self):
                    super().close()
                    closed.append(self)

            factory = sessionmaker(
                connection, class_=TrackedSession, expire_on_commit=False
            )
            monkeypatch.setattr(
                database_session, "get_session_factory", lambda: factory
            )
            application = create_app()
            application.dependency_overrides[get_settings] = lambda: settings
            with TestClient(application) as client:
                yield ReportContext(
                    client=client,
                    connection=connection,
                    engine=reports_engine,
                    settings=settings,
                    user_id=owner_id,
                    other_user_id=other_id,
                    headers={"Authorization": f"Bearer {owner_token}"},
                    other_headers={"Authorization": f"Bearer {other_token}"},
                    sessions=closed,
                )
        finally:
            connection.rollback()
            connection.exec_driver_sql("SET search_path TO public")
            connection.execute(DropSchema(schema, cascade=True))
            connection.commit()


def create(reports, **changes):
    response = reports.client.post(
        REPORTS, headers=reports.headers, json=payload(**changes)
    )
    assert response.status_code == 201, response.json()
    return response.json()


@pytest.mark.parametrize("with_analysis", [False, True])
def test_create_report_persists_in_postgresql_with_optional_analysis(
    reports, with_analysis, caplog
):
    data = create(reports, **({"analysis": analysis()} if with_analysis else {}))
    assert data["user_id"] == str(reports.user_id)
    assert data["status"] == "active"
    assert data["object_type"] == "audífonos bluetooth"
    assert data["primary_color"] == "negro"
    assert data["secondary_colors"] == ["azul"]
    assert data["private_feature"] == payload()["private_feature"]
    assert data["created_at"] and data["updated_at"]
    with Session(reports.connection) as session:
        saved = session.get(ObjectReport, UUID(data["id"]))
        assert saved.user_id == reports.user_id
        assert saved.created_at.tzinfo is not None
        assert saved.description == data["description"]
        analyses = session.scalars(select(ImageAnalysis)).all()
        assert len(analyses) == int(with_analysis)
        if with_analysis:
            assert analyses[0].report_id == saved.id
            assert analyses[0].provider == "gemini"
            assert analyses[0].model == reports.settings.gemini_model
            assert analyses[0].extracted_data == analysis()["extracted_data"]
            assert data["analysis"]["extracted_data"] == analyses[0].extracted_data
            assert data["analysis"]["confidence"] == "alta"
        else:
            assert data["analysis"] is None
    assert len(reports.sessions) == 1  # Auth and reports share one closed session.
    assert reports.headers["Authorization"] not in caplog.text
    assert data["private_feature"] not in caplog.text


def test_analysis_failure_rolls_back_report_and_session_remains_usable(reports, caplog):
    def fail_analysis(mapper, connection, target):
        raise SQLAlchemyError("internal-database-secret")

    event.listen(ImageAnalysis, "before_insert", fail_analysis)
    try:
        response = reports.client.post(
            REPORTS, headers=reports.headers, json=payload(analysis=analysis())
        )
    finally:
        event.remove(ImageAnalysis, "before_insert", fail_analysis)
    assert response.status_code == 503
    assert "internal-database-secret" not in response.text + caplog.text
    with Session(reports.connection) as session:
        assert session.scalar(select(func.count()).select_from(ObjectReport)) == 0
        assert session.scalar(select(func.count()).select_from(ImageAnalysis)) == 0
    assert len(reports.sessions) == 1
    assert create(reports)["status"] == "active"


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_failed_mutation_rolls_back_and_closes_the_session(reports, method, caplog):
    created = create(reports)
    url = f"{REPORTS}/{created['id']}"

    def fail_update(mapper, connection, target):
        raise SQLAlchemyError("internal-update-secret")

    event.listen(ObjectReport, "before_update", fail_update)
    try:
        options = {"json": {"location": "Biblioteca"}} if method == "patch" else {}
        response = getattr(reports.client, method)(
            url, headers=reports.headers, **options
        )
    finally:
        event.remove(ObjectReport, "before_update", fail_update)
    assert response.status_code == 503
    assert "internal-update-secret" not in response.text + caplog.text
    assert len(reports.sessions) == 2
    assert reports.client.get(url, headers=reports.headers).json() == created


def test_list_pagination_filters_and_descending_order_only_include_owner(reports):
    first = create(reports, analysis=analysis())
    second = create(reports, report_type="found")
    third = create(reports)
    assert (
        reports.client.post(
            REPORTS, headers=reports.other_headers, json=payload()
        ).status_code
        == 201
    )
    assert (
        reports.client.delete(
            f"{REPORTS}/{first['id']}", headers=reports.headers
        ).status_code
        == 204
    )
    response = reports.client.get(f"{REPORTS}/me", headers=reports.headers)
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [
        third["id"],
        second["id"],
        first["id"],
    ]
    assert (body["total"], body["limit"], body["offset"]) == (3, 20, 0)
    page = reports.client.get(
        f"{REPORTS}/me?limit=1&offset=1", headers=reports.headers
    ).json()
    assert page["total"] == 3 and page["items"][0]["id"] == second["id"]
    filtered = reports.client.get(
        f"{REPORTS}/me?report_type=lost&status=cancelled", headers=reports.headers
    ).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["analysis"]["provider"] == "gemini"
    empty = reports.client.get(
        f"{REPORTS}/me?offset=100", headers=reports.headers
    ).json()
    assert empty["items"] == [] and empty["total"] == 3


def test_list_loads_analyses_in_a_constant_number_of_queries(reports):
    for _ in range(4):
        create(reports, analysis=analysis())
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and (
            "object_reports" in statement or "image_analyses" in statement
        ):
            statements.append(statement)

    event.listen(reports.engine, "before_cursor_execute", capture)
    try:
        response = reports.client.get(f"{REPORTS}/me", headers=reports.headers)
    finally:
        event.remove(reports.engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 4
    assert len(statements) == 3  # Count + reports + batched analyses, never N+1.


def test_owner_detail_and_private_feature_are_returned(reports):
    created = create(reports, analysis=analysis())
    response = reports.client.get(f"{REPORTS}/{created['id']}", headers=reports.headers)
    assert response.status_code == 200
    assert response.json() == created


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
@pytest.mark.parametrize("exists", [True, False])
def test_foreign_and_missing_reports_have_identical_404(reports, method, exists):
    report_id = create(reports)["id"] if exists else str(uuid4())
    options = {"json": {"description": "Changed"}} if method == "patch" else {}
    response = getattr(reports.client, method)(
        f"{REPORTS}/{report_id}", headers=reports.other_headers, **options
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Reporte no encontrado."}
    if exists:
        own = reports.client.get(
            f"{REPORTS}/{report_id}", headers=reports.headers
        ).json()
        assert own["status"] == "active"
        assert own["description"] == payload()["description"]


def test_partial_update_clears_nullable_fields_and_preserves_history(reports):
    original = create(reports, analysis=analysis())
    response = reports.client.patch(
        f"{REPORTS}/{original['id']}",
        headers=reports.headers,
        json={"description": "  Una   descripción nueva ", "brand": None},
    )
    assert response.status_code == 200
    changed = response.json()
    assert changed["description"] == "Una descripción nueva"
    assert changed["brand"] is None
    assert changed["analysis"] == original["analysis"]
    assert changed["created_at"] == original["created_at"]
    assert changed["updated_at"] > original["updated_at"]
    assert changed["location"] == original["location"]
    with Session(reports.connection) as session:
        saved = session.get(ObjectReport, UUID(original["id"]))
        assert saved.brand is None and saved.description == changed["description"]


@pytest.mark.parametrize("status", ["resolved", "cancelled"])
def test_status_transition_disallows_later_edit_or_cancel(reports, status):
    created = create(reports)
    url = f"{REPORTS}/{created['id']}"
    assert (
        reports.client.patch(
            url, headers=reports.headers, json={"status": status}
        ).status_code
        == 200
    )
    assert (
        reports.client.patch(
            url, headers=reports.headers, json={"description": "Changed"}
        ).status_code
        == 409
    )
    assert reports.client.delete(url, headers=reports.headers).status_code == 409


def test_delete_is_logical_and_keeps_analysis(reports):
    created = create(reports, analysis=analysis())
    url = f"{REPORTS}/{created['id']}"
    response = reports.client.delete(url, headers=reports.headers)
    assert response.status_code == 204 and response.content == b""
    with Session(reports.connection) as session:
        saved = session.get(ObjectReport, UUID(created["id"]))
        assert saved.status == "cancelled"
        assert session.scalar(select(func.count()).select_from(ObjectReport)) == 1
        assert session.scalar(select(func.count()).select_from(ImageAnalysis)) == 1
    assert (
        reports.client.get(url, headers=reports.headers).json()["status"] == "cancelled"
    )
    assert (
        reports.client.patch(
            url, headers=reports.headers, json={"status": "active"}
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"event_date": (date.today() + timedelta(days=1)).isoformat()},
        {"report_type": "invalid"},
        {"status": "invalid"},
        {"status": "resolved"},
        {"user_id": str(uuid4())},
        {"id": str(uuid4())},
        {"created_at": "2026-01-01"},
        {"image_path": "local-test-only"},
        {"analysis": {**analysis(), "provider": "other"}},
        {"analysis": {**analysis(), "model": "client-selected"}},
        {"analysis": {**analysis(), "confidence": "invalid"}},
        {"analysis": {**analysis(), "extracted_data": {"image": "test-only"}}},
    ],
)
def test_create_rejects_invalid_or_server_owned_fields(reports, changes):
    response = reports.client.post(
        REPORTS, headers=reports.headers, json=payload(**changes)
    )
    assert response.status_code == 422
    assert '"input"' not in response.text
    with Session(reports.connection) as session:
        assert session.scalar(select(func.count()).select_from(ObjectReport)) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": str(uuid4())},
        {"report_type": "found"},
        {"id": str(uuid4())},
        {"created_at": "2026-01-01"},
        {"analysis": analysis()},
        {"status": "invalid"},
        {"event_date": (date.today() + timedelta(days=1)).isoformat()},
        {},
        {"location": None},
    ],
)
def test_patch_rejects_immutable_or_invalid_fields(reports, changes):
    created = create(reports)
    response = reports.client.patch(
        f"{REPORTS}/{created['id']}", headers=reports.headers, json=changes
    )
    assert response.status_code == 422
    unchanged = reports.client.get(
        f"{REPORTS}/{created['id']}", headers=reports.headers
    ).json()
    assert unchanged == created


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "offset=-1", "report_type=invalid", "status=invalid"],
)
def test_invalid_pagination_and_filters_return_422(reports, query):
    assert (
        reports.client.get(f"{REPORTS}/me?{query}", headers=reports.headers).status_code
        == 422
    )


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", REPORTS, payload()),
        ("get", f"{REPORTS}/me", None),
        ("get", f"{REPORTS}/{uuid4()}", None),
        ("patch", f"{REPORTS}/{uuid4()}", {"description": "Changed"}),
        ("delete", f"{REPORTS}/{uuid4()}", None),
    ],
)
@pytest.mark.parametrize("token_kind", ["missing", "invalid", "inactive"])
def test_every_route_requires_valid_jwt_and_active_user(
    reports, method, path, body, token_kind
):
    headers = {}
    if token_kind == "invalid":
        headers = {"Authorization": "Bearer not-a-real-token"}
    if token_kind == "inactive":
        with Session(reports.connection) as session:
            session.get(User, reports.user_id).is_active = False
            session.commit()
        headers = reports.headers
    response = reports.client.request(method, path, headers=headers, json=body)
    assert response.status_code == (403 if token_kind == "inactive" else 401)
    if response.status_code == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_stale_write_is_rejected_without_losing_the_newer_data(reports):
    created = create(reports)
    with Session(reports.connection, expire_on_commit=False) as session:
        repository = SQLAlchemyObjectReportRepository(session)
        old = repository.get_by_id_and_user(UUID(created["id"]), reports.user_id)
    url = f"{REPORTS}/{created['id']}"
    assert (
        reports.client.patch(
            url, headers=reports.headers, json={"location": "Biblioteca"}
        ).status_code
        == 200
    )
    with Session(reports.connection) as session:
        repo = SQLAlchemyObjectReportRepository(session)
        with pytest.raises(ReportConflictError):
            repo.update(
                replace(
                    old,
                    attributes=ReportAttributes(
                        **{**asdict(old.attributes), "description": "Stale write"}
                    ),
                )
            )
    assert reports.client.delete(url, headers=reports.headers).status_code == 204
    with Session(reports.connection) as session:
        with pytest.raises(ReportNotActiveError):
            SQLAlchemyObjectReportRepository(session).update(old)
    assert (
        reports.client.get(url, headers=reports.headers).json()["location"]
        == "Biblioteca"
    )


def test_alembic_reports_no_schema_differences(reports):
    config = migration_config()
    config.attributes["connection"] = reports.connection
    command.check(config)
    assert reports.connection.scalar(text("SELECT 1")) == 1
