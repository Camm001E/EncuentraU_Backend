from typing import Protocol
from uuid import UUID

from app.domain.object_reports import (
    ObjectReport,
    ReportPage,
    ReportStatus,
    ReportType,
)


class ObjectReportRepository(Protocol):
    def create(self, report: ObjectReport) -> ObjectReport:
        """Persist the report and optional analysis in a single transaction."""
        ...

    def list_by_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        offset: int,
        report_type: ReportType | None = None,
        status: ReportStatus | None = None,
    ) -> ReportPage: ...

    def get_by_id_and_user(
        self, report_id: UUID, user_id: UUID
    ) -> ObjectReport | None: ...

    def update(self, report: ObjectReport) -> ObjectReport:
        """Reject stale versions and reports that are no longer active."""
        ...

    def cancel(self, report: ObjectReport) -> None:
        """Set cancelled without deleting the report or its analyses."""
        ...
