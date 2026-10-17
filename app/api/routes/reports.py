from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.auth_errors import AuthRoute
from app.api.dependencies.authentication import get_current_user
from app.api.dependencies.object_reports import get_report_repository
from app.api.schemas.object_reports import (
    ReportCreate,
    ReportListResponse,
    ReportResponse,
    ReportUpdate,
)
from app.application.object_reports import (
    CancelMyObjectReport,
    CreateObjectReport,
    GetMyObjectReport,
    ListMyObjectReports,
    UpdateMyObjectReport,
)
from app.core.config import Settings, get_settings
from app.domain.object_reports import ReportStatus, ReportType
from app.domain.ports.object_report_repository import ObjectReportRepository
from app.domain.users import User

router = APIRouter(prefix="/reports", tags=["reports"], route_class=AuthRoute)
CurrentUser = Annotated[User, Depends(get_current_user)]
Repository = Annotated[ObjectReportRepository, Depends(get_report_repository)]


@router.post("", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
def create_report(
    body: ReportCreate,
    user: CurrentUser,
    repository: Repository,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReportResponse:
    result = CreateObjectReport(repository, settings.gemini_model)(
        user_id=user.id,
        report_type=body.report_type,
        attributes=body.to_attributes(),
        analysis=body.analysis.to_domain() if body.analysis is not None else None,
    )
    return ReportResponse.from_report(result)


@router.get("/me", response_model=ReportListResponse)
def list_my_reports(
    user: CurrentUser,
    repository: Repository,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    report_type: ReportType | None = None,
    status: ReportStatus | None = None,
) -> ReportListResponse:
    return ReportListResponse.from_page(
        ListMyObjectReports(repository)(
            user.id, limit=limit, offset=offset, report_type=report_type, status=status
        )
    )


@router.get("/{report_id}", response_model=ReportResponse)
def get_my_report(
    report_id: UUID, user: CurrentUser, repository: Repository
) -> ReportResponse:
    return ReportResponse.from_report(GetMyObjectReport(repository)(report_id, user.id))


@router.patch("/{report_id}", response_model=ReportResponse)
def update_my_report(
    report_id: UUID, body: ReportUpdate, user: CurrentUser, repository: Repository
) -> ReportResponse:
    result = UpdateMyObjectReport(repository)(
        report_id, user.id, body.model_dump(exclude_unset=True)
    )
    return ReportResponse.from_report(result)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_my_report(
    report_id: UUID, user: CurrentUser, repository: Repository
) -> Response:
    CancelMyObjectReport(repository)(report_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
