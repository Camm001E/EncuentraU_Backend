from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "EncuentraU AI API"
    api_prefix: str = "/api/v1"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash"
    max_image_size_mb: int = 10
    cors_origins: str = "http://localhost:3000,http://localhost:8080"
    database_url: SecretStr | None = Field(default=None, repr=False)
    jwt_secret_key: SecretStr | None = Field(default=None, repr=False)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=60, gt=0)

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        if len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET_KEY debe contener al menos 32 bytes.")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value().strip()
        if not raw:
            return None
        try:
            parsed = urlsplit(raw)
            valid = (
                parsed.scheme in {"postgresql", "postgresql+psycopg"}
                and parsed.hostname
                and parsed.path.strip("/")
                and not parsed.fragment
            )
            _ = parsed.port  # Validate without including its input in errors.
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "DATABASE_URL debe ser una URL PostgreSQL válida."
            ) from None
        return SecretStr(raw)

    @property
    def max_image_size_bytes(self) -> int:
        return self.max_image_size_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [origin.strip() for origin in self.cors_origins.split(",")]
        return [origin for origin in origins if origin]


@lru_cache
def get_settings() -> Settings:
    return Settings()
