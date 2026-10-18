"""Local, interactive administration provisioning. No public admin registration."""

import getpass
from uuid import uuid4

from pydantic import ValidationError

from app.api.schemas.authentication import RegisterRequest
from app.domain.authentication import AuthenticationError, DuplicateUserError
from app.domain.users import User, UserRole
from app.infrastructure.auth_security import get_password_hasher
from app.infrastructure.database.engine import DatabaseConfigurationError
from app.infrastructure.database.session import get_session_factory
from app.infrastructure.database.user_repository import SQLAlchemyUserRepository


def main(*, input_fn=None, password_fn=None, session_factory=None) -> int:
    input_fn = input_fn or input
    password_fn = password_fn or getpass.getpass
    try:
        full_name = input_fn("Nombre: ")
        email = input_fn("Email: ")
        student_code = input_fn("Código: ")
        password = password_fn("Contraseña: ")
        confirmation = password_fn("Repite la contraseña: ")
        if password != confirmation:
            print("Las contraseñas no coinciden.")
            return 1
        request = RegisterRequest(
            full_name=full_name,
            email=email,
            student_code=student_code,
            password=password,
        )
        del password, confirmation
        factory = session_factory or get_session_factory()
        with factory() as session:
            repository = SQLAlchemyUserRepository(session)
            if repository.get_by_email(
                str(request.email)
            ) or repository.get_by_student_code(request.student_code):
                raise DuplicateUserError
            repository.create(
                User(
                    id=uuid4(),
                    full_name=request.full_name,
                    email=str(request.email),
                    student_code=request.student_code,
                    password_hash=get_password_hasher().hash(
                        request.password.get_secret_value()
                    ),
                    role=UserRole.ADMIN,
                    is_active=True,
                )
            )
        print("Administrador creado correctamente.")
        return 0
    except (ValidationError, EOFError, KeyboardInterrupt):
        print("No se creó el administrador. Revisa los datos obligatorios.")
        return 1
    except (AuthenticationError, DatabaseConfigurationError):
        print("No se creó el administrador. Revisa duplicados y la base.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
