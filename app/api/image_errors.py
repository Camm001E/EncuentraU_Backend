from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.report_images import (
    ImageNotFoundError,
    ImageTooLargeError,
    ImageTypeError,
    ImageValidationError,
    ReportImageError,
)


def register_image_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ReportImageError)
    async def image_error(request: Request, exc: ReportImageError) -> JSONResponse:
        if isinstance(exc, ImageNotFoundError):
            code = 404
        elif isinstance(exc, ImageTooLargeError):
            code = 413
        elif isinstance(exc, ImageTypeError):
            code = 415
        elif isinstance(exc, ImageValidationError):
            code = 422
        else:
            code = 503
        return JSONResponse(status_code=code, content={"detail": exc.message})
