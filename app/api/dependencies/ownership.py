from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.dependencies.authentication import get_auth_session, get_current_user
from app.domain.ownership import require_admin
from app.domain.ports.ownership import ConversationRepository, OwnershipClaimRepository
from app.domain.users import User
from app.infrastructure.database.conversation_repository import (
    SQLAlchemyConversationRepository,
)
from app.infrastructure.database.ownership_repository import (
    SQLAlchemyOwnershipClaimRepository,
)


def get_claim_repository(
    session: Annotated[Session, Depends(get_auth_session)],
) -> OwnershipClaimRepository:
    return SQLAlchemyOwnershipClaimRepository(session)


def get_conversation_repository(
    session: Annotated[Session, Depends(get_auth_session)],
) -> ConversationRepository:
    return SQLAlchemyConversationRepository(session)


def get_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    return require_admin(user)
