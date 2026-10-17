import secrets
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import jwt
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.domain.authentication import InvalidAccessTokenError
from app.infrastructure.auth_security import JWTAccessTokenService, get_password_hasher


def test_unknown_user_also_performs_hash_verification(monkeypatch):
    passwords = get_password_hasher()
    verify = Mock(return_value=True)
    monkeypatch.setattr(passwords._hasher, "verify", verify)
    assert passwords.verify("unknown-password", None) is False
    verify.assert_called_once()


def test_password_hash_uses_random_salt_and_does_not_strip_password():
    passwords = get_password_hasher()
    first = passwords.hash("  clave segura  ")
    second = passwords.hash("  clave segura  ")
    assert first != second
    assert passwords.verify("  clave segura  ", first)
    assert not passwords.verify("clave segura", first)
    assert not passwords.verify("any", "invalid-hash")


def test_jwt_settings_are_safe_and_optional():
    secret = secrets.token_hex(32)
    settings = Settings(_env_file=None, jwt_secret_key=secret)
    assert isinstance(settings.jwt_secret_key, SecretStr)
    assert secret not in repr(settings)
    assert secret not in settings.model_dump_json()
    assert settings.jwt_algorithm == "HS256"
    assert settings.access_token_expire_minutes == 60
    assert Settings(_env_file=None, jwt_secret_key="").jwt_secret_key is None


@pytest.mark.parametrize(
    "changes",
    [
        {"jwt_secret_key": "short-secret"},
        {"jwt_algorithm": "none"},
        {"jwt_algorithm": "HS384"},
        {"access_token_expire_minutes": 0},
        {"access_token_expire_minutes": -1},
    ],
)
def test_invalid_jwt_configuration_is_rejected_without_exposing_secrets(changes):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **changes)
    assert "short-secret" not in str(error.value)


@pytest.mark.parametrize("missing", ["sub", "role", "iat", "exp"])
def test_jwt_requires_all_security_claims(missing):
    secret = secrets.token_hex(32)
    service = JWTAccessTokenService(Settings(_env_file=None, jwt_secret_key=secret))
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid4()),
        "role": "student",
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    del payload[missing]
    with pytest.raises(InvalidAccessTokenError):
        service.decode(jwt.encode(payload, secret, algorithm="HS256"))


@pytest.mark.parametrize(
    "changes", [{"sub": "not-a-uuid"}, {"role": "superadmin"}, {"iat": "invalid"}]
)
def test_jwt_rejects_invalid_security_claims(changes):
    secret = secrets.token_hex(32)
    service = JWTAccessTokenService(Settings(_env_file=None, jwt_secret_key=secret))
    payload = {
        "sub": str(uuid4()),
        "role": "student",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=1),
        **changes,
    }
    with pytest.raises(InvalidAccessTokenError):
        service.decode(jwt.encode(payload, secret, algorithm="HS256"))


def test_jwt_rejects_other_signing_keys_and_unsigned_tokens():
    secret = secrets.token_hex(32)
    service = JWTAccessTokenService(Settings(_env_file=None, jwt_secret_key=secret))
    payload = {
        "sub": str(uuid4()),
        "role": "student",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    for token in (
        jwt.encode(payload, secrets.token_hex(32), algorithm="HS256"),
        jwt.encode(payload, secret, algorithm="HS384"),
        jwt.encode(payload, None, algorithm="none"),
    ):
        with pytest.raises(InvalidAccessTokenError):
            service.decode(token)
