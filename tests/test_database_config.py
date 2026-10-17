import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.infrastructure.database.engine import (
    DatabaseConfigurationError,
    create_database_engine,
)


def test_database_configuration_is_optional() -> None:
    settings = Settings(_env_file=None, database_url=None)
    assert settings.database_url is None


def test_database_url_is_hidden_in_settings_and_serialization() -> None:
    password = "example-test-value"
    settings = Settings(
        _env_file=None,
        database_url=f"postgresql+psycopg://example:{password}@localhost/example",
    )
    assert isinstance(settings.database_url, SecretStr)
    assert password not in repr(settings)
    assert password not in settings.model_dump_json()


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///example.db",
        "not-a-url",
        "postgresql://localhost",
        "postgresql://example:example-test-value@localhost:wrong/example",
        "postgresql://example:example-test-value@/example",
    ],
)
def test_invalid_database_urls_have_controlled_errors(url: str) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url=url)
    assert "DATABASE_URL" in str(error.value)
    assert url not in str(error.value)
    assert "example-test-value" not in str(error.value)


def test_empty_database_url_is_unconfigured() -> None:
    assert Settings(_env_file=None, database_url=" ").database_url is None


def test_engine_uses_psycopg_three_and_hides_parameters() -> None:
    engine = create_database_engine(
        SecretStr("postgresql://example:example-test-value@localhost/example")
    )
    try:
        assert engine.dialect.driver == "psycopg"
        assert engine.echo is False
        assert engine.hide_parameters is True
        assert "example-test-value" not in repr(engine.url)
    finally:
        engine.dispose()


@pytest.mark.parametrize("url", [None, SecretStr("invalid-example-test-value")])
def test_engine_configuration_errors_never_expose_urls(url: SecretStr | None) -> None:
    with pytest.raises(DatabaseConfigurationError) as error:
        create_database_engine(url)
    assert "example-test-value" not in str(error.value)
