from uuid import uuid4

from app.domain.authentication import (
    AuthenticatedUser,
    DuplicateUserError,
    InactiveUserError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
)
from app.domain.ports.auth_security import AccessTokenService, PasswordHasher
from app.domain.ports.user_repository import UserRepository
from app.domain.users import (
    User,
    normalize_email,
    normalize_full_name,
    normalize_student_code,
)


class RegisterUser:
    def __init__(self, repository: UserRepository, passwords: PasswordHasher):
        self.repository = repository
        self.passwords = passwords

    def __call__(
        self, *, full_name: str, email: str, student_code: str, password: str
    ) -> User:
        email = normalize_email(email)
        student_code = normalize_student_code(student_code)
        if self.repository.get_by_email(email) is not None:
            raise DuplicateUserError
        if self.repository.get_by_student_code(student_code) is not None:
            raise DuplicateUserError
        return self.repository.create(
            User(
                id=uuid4(),
                full_name=normalize_full_name(full_name),
                email=email,
                student_code=student_code,
                password_hash=self.passwords.hash(password),
            )
        )


class LoginUser:
    def __init__(
        self,
        repository: UserRepository,
        passwords: PasswordHasher,
        tokens: AccessTokenService,
    ):
        self.repository = repository
        self.passwords = passwords
        self.tokens = tokens

    def __call__(self, *, email: str, password: str) -> AuthenticatedUser:
        user = self.repository.get_by_email(normalize_email(email))
        valid = self.passwords.verify(password, user.password_hash if user else None)
        if user is None or not valid:
            raise InvalidCredentialsError
        if not user.is_active:
            raise InactiveUserError
        return AuthenticatedUser(user=user, token=self.tokens.issue(user))


class GetCurrentUser:
    def __init__(self, repository: UserRepository, tokens: AccessTokenService):
        self.repository = repository
        self.tokens = tokens

    def __call__(self, token: str) -> User:
        user = self.repository.get_by_id(self.tokens.decode(token))
        if user is None:
            raise InvalidAccessTokenError
        if not user.is_active:
            raise InactiveUserError
        # Current role and active state always come from the database.
        return user
