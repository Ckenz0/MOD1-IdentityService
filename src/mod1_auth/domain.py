from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    display_name: str
    password_hash: str
    is_active: bool
    created_at: datetime


class DuplicateEmailError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class PasswordChangeRejectedError(Exception):
    pass
