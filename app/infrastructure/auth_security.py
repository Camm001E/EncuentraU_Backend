import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import Settings
from app.domain.authentication import (
    AccessToken,
    AuthenticationUnavailableError,
    InvalidAccessTokenError,
)
from app.domain.users import User, UserRole


class Argon2PasswordHasher:
    def __init__(self) -> None:
        self._hasher = PasswordHash.recommended()
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(32))

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str | None) -> bool:
        try:
            valid = self._hasher.verify(password, password_hash or self._dummy_hash)
        except (UnknownHashError, ValueError):
            return False
        return password_hash is not None and valid


@lru_cache
def get_password_hasher() -> Argon2PasswordHasher:
    return Argon2PasswordHasher()


class JWTAccessTokenService:
    def __init__(self, settings: Settings):
        if settings.jwt_secret_key is None:
            raise AuthenticationUnavailableError
        self._key = settings.jwt_secret_key.get_secret_value()
        self._algorithm = settings.jwt_algorithm
        self._lifetime = timedelta(minutes=settings.access_token_expire_minutes)

    def issue(self, user: User) -> AccessToken:
        now = datetime.now(UTC)
        value = jwt.encode(
            {
                "sub": str(user.id),
                "role": user.role.value,
                "iat": now,
                "exp": now + self._lifetime,
            },
            self._key,
            algorithm=self._algorithm,
        )
        return AccessToken(value=value, expires_in=int(self._lifetime.total_seconds()))

    def decode(self, token: str) -> UUID:
        try:
            payload = jwt.decode(
                token,
                self._key,
                algorithms=[self._algorithm],
                options={"require": ["sub", "role", "iat", "exp"]},
            )
            UserRole(payload["role"])
            if payload["exp"] <= payload["iat"]:
                raise InvalidAccessTokenError
            return UUID(payload["sub"])
        except (InvalidTokenError, ValueError, TypeError, AttributeError):
            raise InvalidAccessTokenError from None
