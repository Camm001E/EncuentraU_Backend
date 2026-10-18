from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from app.domain.report_images import (
    ImageAccess,
    ImageReference,
    ImageUnavailableError,
    ReportImage,
)
from app.infrastructure.database.models import ObjectMatch, ObjectReport
from app.infrastructure.database.models import ReportImage as ImageModel


def image_reference(model: ImageModel) -> ImageReference:
    return ImageReference(
        **{name: getattr(model, name) for name in ImageReference.__dataclass_fields__}
    )


def image_record(model: ImageModel) -> ReportImage:
    return ReportImage(
        image_reference(model), model.storage_key, model.original_filename
    )


class SQLAlchemyReportImageRepository:
    def __init__(self, session: Session):
        self.session = session

    @contextmanager
    def transaction(
        self, report_id: UUID, user_id: UUID, *, write: bool = False
    ) -> Iterator[ImageAccess | None]:
        try:
            report = self.session.scalar(
                select(ObjectReport)
                .where(ObjectReport.id == report_id)
                .with_for_update(read=not write)
                .execution_options(populate_existing=True)
            )
            if report is None:
                yield None
            else:
                lost = aliased(ObjectReport)
                found = aliased(ObjectReport)
                participant = False
                if report.user_id != user_id:
                    participant = (
                        self.session.scalar(
                            select(ObjectMatch.id)
                            .join(lost, ObjectMatch.lost_report_id == lost.id)
                            .join(found, ObjectMatch.found_report_id == found.id)
                            .where(
                                or_(
                                    and_(
                                        lost.id == report_id, found.user_id == user_id
                                    ),
                                    and_(
                                        found.id == report_id, lost.user_id == user_id
                                    ),
                                )
                            )
                            .limit(1)
                        )
                        is not None
                    )
                image = self.session.scalar(
                    select(ImageModel)
                    .where(ImageModel.report_id == report_id)
                    .execution_options(populate_existing=True)
                )
                yield ImageAccess(
                    report.user_id,
                    report.status,
                    participant,
                    image_record(image) if image else None,
                )
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            raise ImageUnavailableError from None
        except Exception:
            self.session.rollback()
            raise

    def save(self, image: ReportImage) -> None:
        values = {
            **asdict(image.reference),
            "storage_key": image.storage_key,
            "original_filename": image.original_filename,
        }
        model = self.session.get(ImageModel, image.reference.id)
        if model is None:
            self.session.add(ImageModel(**values))
        else:
            for name, value in values.items():
                setattr(model, name, value)
        self.session.flush()

    def delete(self, report_id: UUID) -> None:
        model = self.session.scalar(
            select(ImageModel).where(ImageModel.report_id == report_id)
        )
        if model is not None:
            self.session.delete(model)
            self.session.flush()
