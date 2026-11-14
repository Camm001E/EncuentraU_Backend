from dataclasses import dataclass, field

from app.domain.users import User


@dataclass(frozen=True, slots=True)
class AccessToken:
    value: str = field(repr=False)
    expires_in: int


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    user: User
    token: AccessToken


class AuthenticationError(Exception):
    message = "No se pudo completar la autenticación."


class DuplicateUserError(AuthenticationError):
    message = "El correo o el código estudiantil ya está registrado."


class InvalidCredentialsError(AuthenticationError):
    message = "Correo o contraseña incorrectos."


class InvalidAccessTokenError(AuthenticationError):
    message = "No se pudieron validar las credenciales."


class InactiveUserError(AuthenticationError):
    message = "El usuario está inactivo."


class AuthenticationUnavailableError(AuthenticationError):
    message = "El servicio de autenticación no está disponible."


class EmailVerificationRequiredError(AuthenticationError):
    message = "Verifica tu correo antes de iniciar sesión."


class InvalidVerificationCodeError(AuthenticationError):
    message = "El código no es válido o venció. Solicita otro si es necesario."


class EmailDeliveryUnavailableError(AuthenticationError):
    message = "No pudimos enviar el código. Tu cuenta se conserva; intenta más tarde."


class VerificationRateLimitError(AuthenticationError):
    message = "Espera antes de solicitar otro código."

    def __init__(self, retry_after: int):
        self.retry_after = max(1, retry_after)
