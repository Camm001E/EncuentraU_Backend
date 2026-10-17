from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.object_matches import (
    MatchNotFoundError,
    MatchValidationError,
    ObjectMatchError,
)


def register_match_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ObjectMatchError)
    async def match_error_handler(
        request: Request, exc: ObjectMatchError
    ) -> JSONResponse:
        if isinstance(exc, MatchNotFoundError):
            code = 404
        elif isinstance(exc, MatchValidationError):
            code = 422
        else:
            code = 503
        return JSONResponse(status_code=code, content={"detail": exc.message})
