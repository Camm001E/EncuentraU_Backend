from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
)

from app.domain.users import (
    User,
    UserRole,
    normalize_email,
    normalize_full_name,
    normalize_student_code,
)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: Annotated[EmailStr, Field(max_length=254)]
    password: Annotated[SecretStr, Field(min_length=1, max_length=128)]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, value: object) -> object:
        return normalize_email(value) if isinstance(value, str) else value


class RegisterRequest(LoginRequest):
    full_name: Annotated[str, Field(min_length=1, max_length=200)]
    student_code: Annotated[
        str, Field(min_length=1, max_length=50, pattern=r"^[A-Z0-9][A-Z0-9._-]*$")
    ]
    password: Annotated[SecretStr, Field(min_length=8, max_length=128)]

    @field_validator("full_name", mode="before")
    @classmethod
    def normalize_name_field(cls, value: object) -> object:
        return normalize_full_name(value) if isinstance(value, str) else value

    @field_validator("student_code", mode="before")
    @classmethod
    def normalize_code_field(cls, value: object) -> object:
        return normalize_student_code(value) if isinstance(value, str) else value


class UserResponse(BaseModel):
    id: UUID
    full_name: str
    email: str
    student_code: str
    role: UserRole
    is_active: bool

    @classmethod
    def from_user(cls, user: User) -> UserResponse:
        return cls(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            student_code=user.student_code,
            role=user.role,
            is_active=user.is_active,
        )


class LoginResponse(BaseModel):
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserResponse
