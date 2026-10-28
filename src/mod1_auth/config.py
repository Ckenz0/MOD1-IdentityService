"""Configuracao validada; valores sensiveis permanecem redigidos."""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr
    database_schema: str = Field(default="mod1_identity", pattern=r"^[a-z_][a-z0-9_]*$")
    jwt_private_key_path: Path
    jwt_issuer: str = Field(min_length=1)
    jwt_audience: str = Field(default="engenharia-software-api", min_length=1)
    access_token_expire_minutes: int = Field(default=30, gt=0)
    password_min_length: int = Field(default=12, ge=12, le=128)
    cors_origins: list[str] = Field(default_factory=list)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        if not url.startswith(("postgresql+psycopg://", "sqlite:///")):
            raise ValueError("Use PostgreSQL/psycopg or temporary SQLite for tests")
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
            ):
                raise ValueError("CORS requires explicit HTTP origins without paths")
        return values
