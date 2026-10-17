from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.application.authentication import GetCurrentUser
from app.core.config import Settings, get_settings
from app.domain.authentication import (
    AuthenticationUnavailableError,
    InvalidAccessTokenError,
)
from app.domain.ports.auth_security import AccessTokenService
from app.domain.ports.user_repository import UserRepository
from app.domain.users import User
from app.infrastructure.auth_security import JWTAccessTokenService
from app.infrastructure.database.engine import DatabaseConfigurationError
from app.infrastructure.database.session import get_session
from app.infrastructure.database.user_repository import SQLAlchemyUserRepository

bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_session() -> Iterator[Session]:
    try:
        yield from get_session()
    except (DatabaseConfigurationError, SQLAlchemyError):
        raise AuthenticationUnavailableError from None


def get_user_repository(
    session: Annotated[Session, Depends(get_auth_session)],
) -> UserRepository:
    return SQLAlchemyUserRepository(session)


def get_token_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AccessTokenService:
    return JWTAccessTokenService(settings)


def get_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    if credentials is None:
        raise InvalidAccessTokenError
    return credentials.credentials


def get_current_user(
    token: Annotated[str, Depends(get_bearer_token)],
    tokens: Annotated[AccessTokenService, Depends(get_token_service)],
    repository: Annotated[UserRepository, Depends(get_user_repository)],
) -> User:
    return GetCurrentUser(repository, tokens)(token)
