from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain.authentication import (
    AuthenticationUnavailableError,
    DuplicateUserError,
)
from app.domain.users import User, UserRole
from app.infrastructure.database.models import User as UserModel


class SQLAlchemyUserRepository:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _to_user(model: UserModel) -> User:
        return User(
            id=model.id,
            full_name=model.full_name,
            email=model.email,
            student_code=model.student_code,
            password_hash=model.password_hash,
            role=UserRole(model.role),
            is_active=model.is_active,
        )

    def _find(self, statement: Select) -> User | None:
        try:
            model = self.session.scalar(statement)
            return self._to_user(model) if model is not None else None
        except SQLAlchemyError:
            raise AuthenticationUnavailableError from None

    def get_by_id(self, user_id: UUID) -> User | None:
        return self._find(select(UserModel).where(UserModel.id == user_id))

    def get_by_email(self, email: str) -> User | None:
        return self._find(select(UserModel).where(func.lower(UserModel.email) == email))

    def get_by_student_code(self, student_code: str) -> User | None:
        return self._find(
            select(UserModel).where(func.upper(UserModel.student_code) == student_code)
        )

    def create(self, user: User) -> User:
        model = UserModel(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            student_code=user.student_code,
            password_hash=user.password_hash,
            role=user.role.value,
            is_active=user.is_active,
        )
        try:
            self.session.add(model)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            constraint = getattr(
                getattr(exc.orig, "diag", None), "constraint_name", None
            )
            if (
                constraint in {"uq_users_email", "uq_users_student_code"}
                or getattr(exc.orig, "sqlite_errorname", None)
                == "SQLITE_CONSTRAINT_UNIQUE"
            ):
                raise DuplicateUserError from None
            raise AuthenticationUnavailableError from None
        except SQLAlchemyError:
            self.session.rollback()
            raise AuthenticationUnavailableError from None
        return self._to_user(model)
