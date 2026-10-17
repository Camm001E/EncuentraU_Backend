from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.domain.authentication import AuthenticationUnavailableError, DuplicateUserError
from app.domain.users import User
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import User as UserModel
from app.infrastructure.database.user_repository import SQLAlchemyUserRepository


def new_user(**changes):
    values = {
        "id": uuid4(),
        "full_name": "Usuario Prueba",
        "email": "usuario@example.com",
        "student_code": "20260001",
        "password_hash": "test-only-hash",
        **changes,
    }
    return User(**values)


@pytest.mark.parametrize("duplicate", ["email", "student_code"])
def test_database_uniqueness_race_rolls_back_and_session_remains_usable(duplicate):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            repo = SQLAlchemyUserRepository(session)
            repo.create(new_user())
            changes = {"email": "otro@example.com", "student_code": "20260002"}
            changes[duplicate] = getattr(new_user(), duplicate)
            with pytest.raises(DuplicateUserError):
                repo.create(new_user(**changes))
            assert session.scalar(select(func.count()).select_from(UserModel)) == 1
            assert repo.create(
                new_user(email="tercero@example.com", student_code="20260003")
            )
    finally:
        engine.dispose()


def test_database_commit_failure_rolls_back_without_exposing_internal_error():
    session = Mock()
    session.commit.side_effect = OperationalError(
        "secret-url", {}, Exception("secret-password")
    )
    with pytest.raises(AuthenticationUnavailableError) as error:
        SQLAlchemyUserRepository(session).create(new_user())
    session.rollback.assert_called_once()
    assert "secret-password" not in str(error.value)
    assert "secret-url" not in str(error.value)
