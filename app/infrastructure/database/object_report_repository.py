from dataclasses import asdict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.domain.object_reports import (
    ATTRIBUTE_FIELDS,
    AnalysisData,
    ImageAnalysis,
    ObjectReport,
    ReportAttributes,
    ReportConflictError,
    ReportError,
    ReportNotActiveError,
    ReportNotFoundError,
    ReportPage,
    ReportPersistenceError,
    ReportStatus,
    ReportType,
)
from app.infrastructure.database.models import ImageAnalysis as AnalysisModel
from app.infrastructure.database.models import ObjectReport as ReportModel


class SQLAlchemyObjectReportRepository:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _to_report(model: ReportModel) -> ObjectReport:
        latest = max(
            model.analyses, key=lambda item: (item.created_at, item.id), default=None
        )
        return ObjectReport(
            id=model.id,
            user_id=model.user_id,
            report_type=ReportType(model.report_type),
            status=ReportStatus(model.status),
            attributes=ReportAttributes(
                **{name: getattr(model, name) for name in ATTRIBUTE_FIELDS}
            ),
            created_at=model.created_at,
            updated_at=model.updated_at,
            analysis=(
                ImageAnalysis(
                    id=latest.id,
                    report_id=latest.report_id,
                    provider=latest.provider,
                    model=latest.model,
                    data=AnalysisData(
                        extracted_data=latest.extracted_data,
                        confidence=latest.confidence,
                    ),
                    created_at=latest.created_at,
                )
                if latest is not None
                else None
            ),
        )

    def create(self, report: ObjectReport) -> ObjectReport:
        model = ReportModel(
            id=report.id,
            user_id=report.user_id,
            report_type=report.report_type.value,
            status=ReportStatus.ACTIVE.value,
            analyses=[],
            **asdict(report.attributes),
        )
        if report.analysis is not None:
            analysis = report.analysis
            model.analyses.append(
                AnalysisModel(
                    id=analysis.id,
                    provider=analysis.provider,
                    model=analysis.model,
                    extracted_data=analysis.data.extracted_data,
                    confidence=analysis.data.confidence.value,
                )
            )
        try:
            self.session.add(model)
            self.session.flush()
            result = self._to_report(model)
            self.session.commit()
            return result
        except SQLAlchemyError:
            self.session.rollback()
            raise ReportPersistenceError from None
        except Exception:
            self.session.rollback()
            raise

    def get_by_id_and_user(self, report_id: UUID, user_id: UUID) -> ObjectReport | None:
        try:
            model = self.session.scalar(
                select(ReportModel)
                .where(ReportModel.id == report_id, ReportModel.user_id == user_id)
                .options(selectinload(ReportModel.analyses))
            )
            return self._to_report(model) if model is not None else None
        except SQLAlchemyError:
            self.session.rollback()
            raise ReportPersistenceError from None

    def list_by_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        offset: int,
        report_type: ReportType | None = None,
        status: ReportStatus | None = None,
    ) -> ReportPage:
        predicates = [ReportModel.user_id == user_id]
        if report_type is not None:
            predicates.append(ReportModel.report_type == report_type.value)
        if status is not None:
            predicates.append(ReportModel.status == status.value)
        try:
            total = self.session.scalar(
                select(func.count()).select_from(ReportModel).where(*predicates)
            )
            models = self.session.scalars(
                select(ReportModel)
                .where(*predicates)
                .order_by(ReportModel.created_at.desc(), ReportModel.id.desc())
                .limit(limit)
                .offset(offset)
                .options(selectinload(ReportModel.analyses))
            ).all()
            return ReportPage(
                items=tuple(self._to_report(model) for model in models),
                total=total,
                limit=limit,
                offset=offset,
            )
        except SQLAlchemyError:
            self.session.rollback()
            raise ReportPersistenceError from None

    def _write(self, report: ObjectReport, *, cancel: bool = False) -> ObjectReport:
        try:
            # Recheck ownership, status and version under a row lock. In particular,
            # a concurrent cancellation cannot be overwritten by an earlier PATCH.
            model = self.session.scalar(
                select(ReportModel)
                .where(
                    ReportModel.id == report.id, ReportModel.user_id == report.user_id
                )
                .with_for_update()
                .execution_options(populate_existing=True)
                .options(selectinload(ReportModel.analyses))
            )
            if model is None:
                raise ReportNotFoundError
            if model.status != ReportStatus.ACTIVE.value:
                raise ReportNotActiveError
            if model.updated_at != report.updated_at:
                raise ReportConflictError
            if not cancel:
                for name, value in asdict(report.attributes).items():
                    setattr(model, name, value)
            model.status = (
                ReportStatus.CANCELLED.value if cancel else report.status.value
            )
            # Even a valid no-op PATCH advances the version deterministically.
            model.updated_at = func.now()
            self.session.flush()
            self.session.refresh(model, attribute_names=["updated_at"])
            result = self._to_report(model)
            self.session.commit()
            return result
        except SQLAlchemyError:
            self.session.rollback()
            raise ReportPersistenceError from None
        except ReportError:
            self.session.rollback()
            raise
        except Exception:
            self.session.rollback()
            raise

    def update(self, report: ObjectReport) -> ObjectReport:
        return self._write(report)

    def cancel(self, report: ObjectReport) -> None:
        self._write(report, cancel=True)
