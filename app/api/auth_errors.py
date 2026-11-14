from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.domain.authentication import (
    AuthenticationError,
    DuplicateUserError,
    EmailVerificationRequiredError,
    InactiveUserError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
    InvalidVerificationCodeError,
    VerificationRateLimitError,
)


class AuthRoute(APIRoute):
    """Validation errors must not echo raw bodies, passwords or extra fields."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={
                        "detail": [
                            {
                                "loc": error["loc"],
                                "msg": error["msg"],
                                "type": error["type"],
                            }
                            for error in exc.errors()
                        ]
                    },
                )

        return handler


def register_auth_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(
        request: Request, exc: AuthenticationError
    ) -> JSONResponse:
        code = {
            DuplicateUserError: status.HTTP_409_CONFLICT,
            InvalidCredentialsError: status.HTTP_401_UNAUTHORIZED,
            InvalidAccessTokenError: status.HTTP_401_UNAUTHORIZED,
            InactiveUserError: status.HTTP_403_FORBIDDEN,
            EmailVerificationRequiredError: status.HTTP_403_FORBIDDEN,
            InvalidVerificationCodeError: status.HTTP_400_BAD_REQUEST,
            VerificationRateLimitError: status.HTTP_429_TOO_MANY_REQUESTS,
        }.get(type(exc), status.HTTP_503_SERVICE_UNAVAILABLE)
        headers = (
            {"WWW-Authenticate": "Bearer"}
            if code == status.HTTP_401_UNAUTHORIZED
            else None
        )
        content = {"detail": exc.message}
        if isinstance(exc, EmailVerificationRequiredError):
            content["code"] = "email_verification_required"
        headers = {**(headers or {}), "Cache-Control": "no-store"}
        if isinstance(exc, VerificationRateLimitError):
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(status_code=code, content=content, headers=headers)
