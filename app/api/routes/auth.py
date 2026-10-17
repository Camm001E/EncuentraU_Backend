from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.auth_errors import AuthRoute
from app.api.dependencies.authentication import (
    get_current_user,
    get_token_service,
    get_user_repository,
)
from app.api.schemas.authentication import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserResponse,
)
from app.application.authentication import LoginUser, RegisterUser
from app.domain.ports.auth_security import AccessTokenService, PasswordHasher
from app.domain.ports.user_repository import UserRepository
from app.domain.users import User
from app.infrastructure.auth_security import get_password_hasher

router = APIRouter(prefix="/auth", tags=["authentication"], route_class=AuthRoute)


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def register(
    body: RegisterRequest,
    repository: Annotated[UserRepository, Depends(get_user_repository)],
    passwords: Annotated[PasswordHasher, Depends(get_password_hasher)],
) -> UserResponse:
    user = RegisterUser(repository, passwords)(
        full_name=body.full_name,
        email=str(body.email),
        student_code=body.student_code,
        password=body.password.get_secret_value(),
    )
    return UserResponse.from_user(user)


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    response: Response,
    tokens: Annotated[AccessTokenService, Depends(get_token_service)],
    repository: Annotated[UserRepository, Depends(get_user_repository)],
    passwords: Annotated[PasswordHasher, Depends(get_password_hasher)],
) -> LoginResponse:
    result = LoginUser(repository, passwords, tokens)(
        email=str(body.email), password=body.password.get_secret_value()
    )
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
