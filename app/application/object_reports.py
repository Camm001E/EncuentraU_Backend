from dataclasses import asdict, replace
from typing import Any
from uuid import UUID, uuid4

from app.domain.object_reports import (
    EDITABLE_FIELDS,
    AnalysisData,
    ImageAnalysis,
    ObjectReport,
    ReportAttributes,
    ReportNotActiveError,
    ReportNotFoundError,
    ReportPage,
    ReportStatus,
    ReportType,
    ReportValidationError,
)
from app.domain.ports.object_report_repository import ObjectReportRepository

ANALYSIS_PROVIDER = "gemini"


class CreateObjectReport:
    def __init__(self, repository: ObjectReportRepository, model: str):
        self.repository = repository
        self.model = model

    def __call__(
        self,
        *,
        user_id: UUID,
        report_type: ReportType,
        attributes: ReportAttributes,
        analysis: AnalysisData | None = None,
    ) -> ObjectReport:
        report_id = uuid4()
        return self.repository.create(
            ObjectReport(
                id=report_id,
                user_id=user_id,
                report_type=ReportType(report_type),
                attributes=attributes,
                analysis=(
                    ImageAnalysis(
                        id=uuid4(),
                        report_id=report_id,
                        provider=ANALYSIS_PROVIDER,
                        model=self.model,
                        data=analysis,
                    )
                    if analysis is not None
                    else None
                ),
            )
        )


class ListMyObjectReports:
    def __init__(self, repository: ObjectReportRepository):
        self.repository = repository

    def __call__(
        self,
        user_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
        report_type: ReportType | None = None,
        status: ReportStatus | None = None,
    ) -> ReportPage:
        if not 1 <= limit <= 100 or offset < 0:
            raise ReportValidationError
        return self.repository.list_by_user(
            user_id, limit=limit, offset=offset, report_type=report_type, status=status
        )


class GetMyObjectReport:
    def __init__(self, repository: ObjectReportRepository):
        self.repository = repository

    def __call__(self, report_id: UUID, user_id: UUID) -> ObjectReport:
        report = self.repository.get_by_id_and_user(report_id, user_id)
        if report is None:
            raise ReportNotFoundError
        return report


class UpdateMyObjectReport:
    def __init__(self, repository: ObjectReportRepository):
        self.repository = repository

    def __call__(
        self, report_id: UUID, user_id: UUID, changes: dict[str, Any]
    ) -> ObjectReport:
        report = GetMyObjectReport(self.repository)(report_id, user_id)
        if report.status != ReportStatus.ACTIVE:
            raise ReportNotActiveError
        if not changes or changes.keys() - EDITABLE_FIELDS:
            raise ReportValidationError
        values = dict(changes)
        try:
            status = ReportStatus(values.pop("status", report.status))
        except ValueError:
            raise ReportValidationError from None
        attributes = ReportAttributes(**{**asdict(report.attributes), **values})
        return self.repository.update(
            replace(report, attributes=attributes, status=status)
        )


class CancelMyObjectReport:
    def __init__(self, repository: ObjectReportRepository):
        self.repository = repository

    def __call__(self, report_id: UUID, user_id: UUID) -> None:
        report = GetMyObjectReport(self.repository)(report_id, user_id)
        if report.status != ReportStatus.ACTIVE:
            raise ReportNotActiveError
        self.repository.cancel(report)
