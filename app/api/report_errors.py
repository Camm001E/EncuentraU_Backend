from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.object_reports import (
    ReportConflictError,
    ReportError,
    ReportNotFoundError,
    ReportValidationError,
)


def register_report_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ReportError)
    async def report_error_handler(request: Request, exc: ReportError) -> JSONResponse:
        if isinstance(exc, ReportNotFoundError):
            code = 404
        elif isinstance(exc, ReportValidationError):
            code = 422
        elif isinstance(exc, ReportConflictError):
            code = 409
        else:
            code = 503
        return JSONResponse(status_code=code, content={"detail": exc.message})
