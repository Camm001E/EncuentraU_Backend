from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.ownership import (
    WorkflowConflict,
    WorkflowError,
    WorkflowForbidden,
    WorkflowNotFound,
    WorkflowValidation,
)


def register_workflow_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(WorkflowError)
    async def workflow_error_handler(
        request: Request, exc: WorkflowError
    ) -> JSONResponse:
        code = {
            WorkflowNotFound: 404,
            WorkflowForbidden: 403,
            WorkflowConflict: 409,
            WorkflowValidation: 422,
        }.get(type(exc), 503)
        return JSONResponse(
            status_code=code,
            content={
                "detail": exc.message,
                "code": "permission_denied" if code == 403 else "workflow_error",
            },
            headers={"Cache-Control": "private, no-store"},
        )
