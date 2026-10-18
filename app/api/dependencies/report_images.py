from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.dependencies.authentication import get_auth_session
from app.application.report_images import ReportImageService
from app.core.config import Settings, get_settings
from app.infrastructure.database.report_image_repository import (
    SQLAlchemyReportImageRepository,
)
from app.infrastructure.image_processor import PillowImageProcessor
from app.infrastructure.local_image_storage import LocalImageStorage


def get_report_image_service(
    session: Annotated[Session, Depends(get_auth_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReportImageService:
    return ReportImageService(
        SQLAlchemyReportImageRepository(session),
        LocalImageStorage(settings.report_image_directory),
        PillowImageProcessor(settings.report_image_max_bytes),
    )
