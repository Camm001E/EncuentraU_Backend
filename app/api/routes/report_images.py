from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.auth_errors import AuthRoute
from app.api.dependencies.authentication import get_current_user
from app.api.dependencies.report_images import get_report_image_service
from app.api.schemas.report_images import ReportImageResponse
from app.application.report_images import ReportImageService
from app.core.config import Settings, get_settings
from app.domain.report_images import ImageTooLargeError
from app.domain.users import User

router = APIRouter(prefix="/reports", tags=["report-images"], route_class=AuthRoute)
CurrentUser = Annotated[User, Depends(get_current_user)]
Service = Annotated[ReportImageService, Depends(get_report_image_service)]
UPLOAD_CHUNK_BYTES = 65_536


@router.put("/{report_id}/image", response_model=ReportImageResponse)
async def upload_image(
    report_id: UUID,
    user: CurrentUser,
    service: Service,
    settings: Annotated[Settings, Depends(get_settings)],
    image: Annotated[UploadFile, File()],
) -> ReportImageResponse:
    try:
        data = bytearray()
        while chunk := await image.read(UPLOAD_CHUNK_BYTES):
            data.extend(chunk)
            if len(data) > settings.report_image_max_bytes:
                raise ImageTooLargeError
        result = await run_in_threadpool(
            service.upload,
            report_id,
            user,
            bytes(data),
            image.filename or "",
            image.content_type or "",
        )
        return ReportImageResponse.from_reference(result)
    finally:
        await image.close()


@router.get("/{report_id}/image", response_model=ReportImageResponse)
def get_image(
    report_id: UUID, user: CurrentUser, service: Service
) -> ReportImageResponse:
    return ReportImageResponse.from_reference(service.metadata(report_id, user))


@router.get("/{report_id}/image/content")
def get_image_content(report_id: UUID, user: CurrentUser, service: Service) -> Response:
    result = service.content(report_id, user)
    return Response(
        result.data,
        media_type=result.reference.content_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "ETag": f'"{result.reference.sha256}"',
        },
    )


@router.delete("/{report_id}/image", status_code=204)
def delete_image(report_id: UUID, user: CurrentUser, service: Service) -> Response:
    service.delete(report_id, user)
    return Response(status_code=204)
