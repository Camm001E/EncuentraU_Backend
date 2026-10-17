from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from app.infrastructure.database import engine as database_engine
from app.main import app


def test_database_health_returns_200_after_real_select(monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr(database_engine, "get_engine", lambda: engine)
    try:
        with TestClient(app) as client:
            response = client.get("/health/database")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "postgresql"}
    finally:
        engine.dispose()


def test_database_health_sanitizes_connection_errors(monkeypatch, caplog) -> None:
    engine = Mock()
    engine.connect.side_effect = OperationalError(
        "example-test-url", {}, Exception("example-test-password internal details")
    )
    monkeypatch.setattr(database_engine, "get_engine", lambda: engine)
    with TestClient(app) as client:
        response = client.get("/health/database")
        assert client.get("/health").status_code == 200
    assert response.status_code == 503
    assert response.json() == {"detail": "La base de datos no está disponible."}
    assert "example-test-password" not in response.text + caplog.text
    assert "example-test-url" not in response.text + caplog.text
    assert "internal details" not in response.text + caplog.text


def test_database_health_is_503_when_unconfigured(monkeypatch) -> None:
    def unconfigured():
        raise database_engine.DatabaseConfigurationError("Base no configurada")

    monkeypatch.setattr(database_engine, "get_engine", unconfigured)
    with TestClient(app) as client:
        assert client.get("/health/database").status_code == 503
        assert client.get("/health").status_code == 200
