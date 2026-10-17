from typing import Protocol
from uuid import UUID

from app.domain.authentication import AccessToken
from app.domain.users import User


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password: str, password_hash: str | None) -> bool:
        """Unknown users also run a hash verification, then return False."""
        ...


class AccessTokenService(Protocol):
    def issue(self, user: User) -> AccessToken: ...

    def decode(self, token: str) -> UUID: ...
