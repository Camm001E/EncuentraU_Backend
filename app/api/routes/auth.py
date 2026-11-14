from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.auth_errors import AuthRoute
from app.api.dependencies.authentication import (
    get_auth_session,
    get_current_user,
    get_token_service,
    get_user_repository,
)
from app.api.schemas.authentication import (
    LoginRequest,
    LoginResponse,
    RecoveryConfirmRequest,
    RecoveryRequest,
    RegisterRequest,
    UserResponse,
    VerifyEmailRequest,
)
from app.application.authentication import LoginUser, RegisterUser
from app.core.config import Settings, get_settings
from app.domain.ports.auth_security import AccessTokenService, PasswordHasher
from app.domain.ports.user_repository import UserRepository
from app.domain.ports.verification_email import VerificationEmailSender
from app.domain.users import User
from app.infrastructure.auth_security import get_password_hasher
from app.infrastructure.database.email_verification import EmailVerification
from app.infrastructure.database.password_recovery import (
    PasswordRecovery,
    send_recovery_in_background,
)
from app.infrastructure.verification_email import SESVerificationEmailSender

router = APIRouter(prefix="/auth", tags=["authentication"], route_class=AuthRoute)


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def register(
    body: RegisterRequest,
    repository: Annotated[UserRepository, Depends(get_user_repository)],
    passwords: Annotated[PasswordHasher, Depends(get_password_hasher)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserResponse:
    user = RegisterUser(repository, passwords)(
        full_name=body.full_name,
        email=str(body.email),
        student_code=body.student_code,
        password=body.password.get_secret_value(),
    )
    result = UserResponse.from_user(user)
    result.email_verification_required = settings.email_verification_required
    return result


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    response: Response,
    tokens: Annotated[AccessTokenService, Depends(get_token_service)],
    repository: Annotated[UserRepository, Depends(get_user_repository)],
    passwords: Annotated[PasswordHasher, Depends(get_password_hasher)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginResponse:
    result = LoginUser(
        repository, passwords, tokens, settings.email_verification_required
    )(email=str(body.email), password=body.password.get_secret_value())
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return LoginResponse(
        access_token=result.token.value,
        expires_in=result.token.expires_in,
        user=UserResponse.from_user(result.user),
    )


@router.get("/me", response_model=UserResponse)
def me(user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return UserResponse.from_user(user)


def get_email_sender(settings: Annotated[Settings, Depends(get_settings)]):
    return SESVerificationEmailSender(settings)


def get_email_verification(
    session: Annotated[Session, Depends(get_auth_session)],
    passwords: Annotated[PasswordHasher, Depends(get_password_hasher)],
    settings: Annotated[Settings, Depends(get_settings)],
    sender: Annotated[VerificationEmailSender, Depends(get_email_sender)],
):
    return EmailVerification(session, passwords, sender, settings)


@router.post("/verification/request")
def request_verification(
    body: LoginRequest,
    response: Response,
    service: Annotated[EmailVerification, Depends(get_email_verification)],
):
    response.headers["Cache-Control"] = "no-store"
    return service.request(str(body.email), body.password.get_secret_value())


@router.post("/verification/confirm")
def confirm_verification(
    body: VerifyEmailRequest,
    response: Response,
    service: Annotated[EmailVerification, Depends(get_email_verification)],
):
    response.headers["Cache-Control"] = "no-store"
    return service.confirm(str(body.email), body.password.get_secret_value(), body.code)


@router.post("/password/request")
def request_password_recovery(
    body: RecoveryRequest,
    response: Response,
    background: BackgroundTasks,
    passwords: Annotated[PasswordHasher, Depends(get_password_hasher)],
    settings: Annotated[Settings, Depends(get_settings)],
    sender: Annotated[VerificationEmailSender, Depends(get_email_sender)],
):
    response.headers["Cache-Control"] = "no-store"
    background.add_task(
        send_recovery_in_background, str(body.email), passwords, sender, settings
    )
    return {"status": "accepted", "retry_after": 60}


def get_password_recovery(
    session: Annotated[Session, Depends(get_auth_session)],
    passwords: Annotated[PasswordHasher, Depends(get_password_hasher)],
    settings: Annotated[Settings, Depends(get_settings)],
    sender: Annotated[VerificationEmailSender, Depends(get_email_sender)],
):
    return PasswordRecovery(session, passwords, sender, settings)


@router.post("/password/confirm")
def confirm_password_recovery(
    body: RecoveryConfirmRequest,
    response: Response,
    service: Annotated[PasswordRecovery, Depends(get_password_recovery)],
):
    response.headers["Cache-Control"] = "no-store"
    return service.confirm(
        str(body.email), body.code, body.new_password.get_secret_value()
    )
