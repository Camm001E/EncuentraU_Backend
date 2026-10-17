from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.dependencies.authentication import get_auth_session
from app.application.matching_service import MatchingService
from app.domain.ports.object_match_repository import ObjectMatchRepository
from app.infrastructure.database.object_match_repository import (
    SQLAlchemyObjectMatchRepository,
)


def get_match_repository(
    session: Annotated[Session, Depends(get_auth_session)],
) -> ObjectMatchRepository:
    return SQLAlchemyObjectMatchRepository(session)


def get_matching_service() -> MatchingService:
    return MatchingService()
