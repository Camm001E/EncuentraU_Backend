from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.dependencies.authentication import get_auth_session
from app.domain.ports.deliveries import DeliveryRepository
from app.infrastructure.database.delivery_repository import SQLAlchemyDeliveryRepository


def get_delivery_repository(
    session: Annotated[Session, Depends(get_auth_session)],
) -> DeliveryRepository:
    return SQLAlchemyDeliveryRepository(session)
