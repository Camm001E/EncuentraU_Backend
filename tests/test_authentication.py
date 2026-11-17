import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.infrastructure.auth_security import get_password_hasher
from app.infrastructure.database import session as database_session
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import User
from app.main import create_app

PASSWORD = "UnaClaveSegura123"
PAYLOAD = {
    "full_name": "Usuario Prueba",
    "email": "usuario@universidad.edu.co",
    "student_code": "20260001",
    "password": PASSWORD,
}
AUTH = "/api/v1/auth"


@dataclass
class AuthContext:
    client: TestClient
    engine: Engine
    settings: Settings
    closed_sessions: list[Session]


@pytest.fixture
def auth(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        hide_parameters=True,
    )
    Base.metadata.create_all(engine)
    closed = []

    class TrackedSession(Session):
        def close(self):
            super().close()
            closed.append(self)

    factory = sessionmaker(engine, class_=TrackedSession, expire_on_commit=False)
    monkeypatch.setattr(database_session, "get_session_factory", lambda: factory)
    settings = Settings(
        _env_file=None, jwt_secret_key=secrets.token_hex(32), database_url=None
    )
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(application) as client:
            yield AuthContext(client, engine, settings, closed)
    finally:
        application.dependency_overrides.clear()
        engine.dispose()


def register(auth, **changes):
    return auth.client.post(f"{AUTH}/register", json={**PAYLOAD, **changes})


def login(auth, **changes):
    return auth.client.post(
        f"{AUTH}/login",
        json={"email": PAYLOAD["email"], "password": PASSWORD, **changes},
    )


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def signed_token(auth, **changes):
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid4()),
        "role": "student",
        "iat": now,
        "exp": now + timedelta(hours=1),
        **changes,
    }
    return jwt.encode(
        payload, auth.settings.jwt_secret_key.get_secret_value(), algorithm="HS256"
    )


def assert_no_passwords(response):
    def check(value):
        if isinstance(value, dict):
            assert not {"password", "password_hash"}.intersection(value)
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(response.json())
    assert PASSWORD not in response.text
    assert "$argon2" not in response.text


def test_register_normalizes_and_persists_only_argon2_hash(auth):
    response = register(
        auth,
        full_name="  Usuario   de\tPrueba  ",
        email="  USUARIO@UNIVERSIDAD.EDU.CO  ",
        student_code="  ab-20260001  ",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["full_name"] == "Usuario de Prueba"
    assert body["email"] == PAYLOAD["email"]
    assert body["student_code"] == "AB-20260001"
    assert body["role"] == "student"
    assert body["is_active"] is True
    with Session(auth.engine) as session:
        saved = session.get(User, UUID(body["id"]))
        assert saved is not None
        assert saved.password_hash != PASSWORD
        assert saved.password_hash.startswith("$argon2id$")
        assert get_password_hasher().verify(PASSWORD, saved.password_hash)
        assert saved.role == "student"
        assert saved.is_active
    assert_no_passwords(response)


@pytest.mark.parametrize(
    "changes",
    [
        {"email": "  USUARIO@UNIVERSIDAD.EDU.CO ", "student_code": "other"},
        {"email": "otro@universidad.edu.co"},
    ],
)
def test_duplicate_email_or_student_code_returns_409(auth, changes):
    assert register(auth).status_code == 201
    response = register(auth, **changes)
    assert response.status_code == 409
    assert_no_passwords(response)
    with Session(auth.engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.parametrize(
    "extra", [{"role": "admin"}, {"is_active": False}, {"password_hash": "hash"}]
)
def test_public_registration_rejects_privileged_fields(auth, extra):
    response = register(auth, **extra)
    assert response.status_code == 422
    assert_no_passwords(response)
    with Session(auth.engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"password": "Corta12"},
        {"password": "x" * 129},
        {"email": "invalid"},
        {"full_name": "  \t "},
        {"student_code": "  "},
        {"student_code": "a b"},
    ],
)
def test_invalid_fields_do_not_echo_password_or_raw_body(auth, changes):
    response = register(auth, **changes)
    assert response.status_code == 422
    assert_no_passwords(response)
    assert '"input"' not in response.text
    assert '"ctx"' not in response.text
    assert changes.get("password", PASSWORD) not in response.text


def test_malformed_json_does_not_echo_password(auth):
    response = auth.client.post(
        f"{AUTH}/register",
        content='{"password":"' + PASSWORD + '",broken',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert_no_passwords(response)


def test_login_returns_jwt_and_current_user(auth, caplog):
    created = register(auth).json()
    response = login(auth, email="  USUARIO@UNIVERSIDAD.EDU.CO  ")
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["user"] == created
    claims = jwt.decode(
        body["access_token"],
        auth.settings.jwt_secret_key.get_secret_value(),
        algorithms=["HS256"],
    )
    assert claims["sub"] == created["id"]
    assert claims["role"] == "student"
    assert claims["exp"] - claims["iat"] == body["expires_in"]
    assert response.headers["Cache-Control"] == "no-store"
    me = auth.client.get(f"{AUTH}/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json() == created
    assert_no_passwords(response)
    assert_no_passwords(me)
    assert PASSWORD not in caplog.text
    assert body["access_token"] not in caplog.text
    assert len(auth.closed_sessions) == 3


def test_wrong_password_and_unknown_email_have_identical_errors(auth):
    register(auth)
    wrong = login(auth, password="Incorrecta123")
    unknown = login(auth, email="desconocido@universidad.edu.co")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.headers["WWW-Authenticate"] == "Bearer"
    assert_no_passwords(wrong)
    assert_no_passwords(unknown)


def test_inactive_user_rejected_at_login_and_me(auth):
    user_id = UUID(register(auth).json()["id"])
    token = login(auth).json()["access_token"]
    with Session(auth.engine) as session:
        session.get(User, user_id).is_active = False
        session.commit()
    assert login(auth).status_code == 403
    assert login(auth, password="Incorrecta123").status_code == 401
    response = auth.client.get(f"{AUTH}/me", headers=bearer(token))
    assert response.status_code == 403
    assert_no_passwords(response)


@pytest.mark.parametrize(
    "authorization", [None, "Basic example", "Bearer", "Bearer not-a-jwt"]
)
def test_missing_or_invalid_token_returns_401(auth, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    response = auth.client.get(f"{AUTH}/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_modified_token_returns_401(auth):
    register(auth)
    token = login(auth).json()["access_token"]
    header, payload, signature = token.split(".")
    signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    response = auth.client.get(
        f"{AUTH}/me", headers=bearer(".".join([header, payload, signature]))
    )
    assert response.status_code == 401


def test_expired_token_returns_401(auth):
    token = signed_token(
        auth,
        iat=datetime.now(UTC) - timedelta(hours=2),
        exp=datetime.now(UTC) - timedelta(hours=1),
    )
    assert auth.client.get(f"{AUTH}/me", headers=bearer(token)).status_code == 401


def test_deleted_user_token_returns_401(auth):
    register(auth)
    token = login(auth).json()["access_token"]
    with Session(auth.engine) as session:
        session.delete(session.scalar(select(User)))
        session.commit()
    assert auth.client.get(f"{AUTH}/me", headers=bearer(token)).status_code == 401


def test_me_uses_current_role_from_database(auth):
    register(auth)
    token = login(auth).json()["access_token"]
    with Session(auth.engine) as session:
        session.scalar(select(User)).role = "admin"
        session.commit()
    response = auth.client.get(f"{AUTH}/me", headers=bearer(token))
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_missing_jwt_key_gives_controlled_503_without_breaking_health(auth):
    auth.settings.jwt_secret_key = None
    response = login(auth)
    assert response.status_code == 503
    assert auth.client.get("/health").status_code == 200
    assert_no_passwords(response)


def test_missing_token_returns_401_even_without_jwt_or_database_configuration():
    with TestClient(create_app()) as client:
        response = client.get(f"{AUTH}/me")
    assert response.status_code == 401


def test_database_unavailable_returns_controlled_503(auth, monkeypatch, caplog):
    from app.infrastructure.database.engine import DatabaseConfigurationError

    def unavailable():
        raise DatabaseConfigurationError("internal-secret-url")

    monkeypatch.setattr(database_session, "get_session_factory", unavailable)
    response = register(auth)
    assert response.status_code == 503
    assert "internal-secret-url" not in response.text + caplog.text
    assert_no_passwords(response)
