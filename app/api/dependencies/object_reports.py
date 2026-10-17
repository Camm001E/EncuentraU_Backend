from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.dependencies.authentication import get_auth_session
from app.domain.ports.object_report_repository import ObjectReportRepository
from app.infrastructure.database.object_report_repository import (
    SQLAlchemyObjectReportRepository,
)


def get_report_repository(
    session: Annotated[Session, Depends(get_auth_session)],
) -> ObjectReportRepository:
    return SQLAlchemyObjectReportRepository(session)
