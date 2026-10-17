from typing import Protocol
from uuid import UUID

from app.domain.users import User


class UserRepository(Protocol):
    def get_by_id(self, user_id: UUID) -> User | None: ...

    def get_by_email(self, email: str) -> User | None: ...

    def get_by_student_code(self, student_code: str) -> User | None: ...

    def create(self, user: User) -> User:
        """Persist atomically, or raise a controlled error after rollback."""
        ...
