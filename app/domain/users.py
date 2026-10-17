from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class UserRole(StrEnum):
    STUDENT = "student"
    ADMIN = "admin"


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_full_name(value: str) -> str:
    return " ".join(value.split())


def normalize_student_code(value: str) -> str:
    return value.strip().upper()


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    full_name: str
    email: str
    student_code: str
    password_hash: str = field(repr=False)
    role: UserRole = UserRole.STUDENT
    is_active: bool = True
