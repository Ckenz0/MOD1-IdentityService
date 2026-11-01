"""Configuracao validada; valores sensiveis permanecem redigidos."""

from email.utils import getaddresses
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from email_validator import EmailNotValidError, validate_email
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
    session_idle_minutes: int = Field(default=15, ge=1, le=1440)
    session_max_hours: int = Field(default=8, ge=1, le=168)
    login_max_failures: int = Field(default=5, ge=1, le=100)
    login_window_minutes: int = Field(default=15, ge=1, le=1440)
    login_lock_minutes: int = Field(default=15, ge=1, le=1440)
    frontend_origin: str = "http://127.0.0.1:5173"
    local_mailbox_enabled: bool = False
    mail_provider: Literal["auto", "local", "resend", "smtp", "disabled"] = "auto"
    resend_api_key: SecretStr | None = Field(default=None, repr=False)
    resend_from: str | None = None
    resend_timeout_seconds: float = Field(default=5, gt=0, le=30)
    mfa_encryption_key: SecretStr | None = None
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "identity@localhost"
    ai_base_url: str | None = None
    ai_api_key: SecretStr | None = None
    ai_model: str = "configured-model"
    ai_simulated: bool = False

    @field_validator("resend_api_key")
    @classmethod
    def validate_resend_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and (
            not value.get_secret_value().strip()
            or any(character.isspace() for character in value.get_secret_value())
        ):
            raise ValueError("Invalid Resend configuration")
        return value

    @field_validator("resend_from")
    @classmethod
    def validate_resend_sender(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "\r" in value or "\n" in value:
            raise ValueError("Invalid Resend sender")
        addresses = getaddresses([value])
        if len(addresses) != 1:
            raise ValueError("Configure exactly one Resend sender")
        try:
            validate_email(addresses[0][1], check_deliverability=False)
        except EmailNotValidError:
            raise ValueError("Configure a valid verified Resend sender") from None
        return value.strip()

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        if not url.startswith(("postgresql+psycopg://", "sqlite:///")):
            raise ValueError("Use PostgreSQL/psycopg or temporary SQLite for tests")
        return value

    @field_validator("frontend_origin")
    @classmethod
    def validate_frontend_origin(cls, value: str) -> str:
        cls.validate_origins([value])
        return value

    @field_validator("ai_base_url")
    @classmethod
    def validate_ai_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parsed = urlsplit(value)
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.scheme not in ("https", "http")
            or (
                parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            )
        ):
            raise ValueError("Use a trusted HTTPS provider or HTTP loopback")
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
