from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, String, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from mod1_auth.database import Base
from mod1_auth.domain import DuplicateEmailError, User, UserNotFoundError


class UserRecord(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "mod1_identity"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def to_user(record: UserRecord) -> User:
    created_at = record.created_at
    if created_at.tzinfo is None:  # SQLite does not preserve timezone metadata.
        created_at = created_at.replace(tzinfo=UTC)
    return User(
        UUID(record.id),
        record.email,
        record.display_name,
        record.password_hash,
        record.is_active,
        created_at.astimezone(UTC),
    )


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, user: User) -> User:
        record = UserRecord(
            id=str(user.id),
            email=user.email,
            display_name=user.display_name,
            password_hash=user.password_hash,
            is_active=user.is_active,
            created_at=user.created_at,
        )
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            if self.get_by_email(user.email) is not None:
                raise DuplicateEmailError("Email already registered") from exc
            raise
        return to_user(record)

    def get_by_email(self, email: str) -> User | None:
        record = self.session.scalar(select(UserRecord).where(UserRecord.email == email))
        return to_user(record) if record is not None else None

    def get_by_id(self, user_id: UUID) -> User | None:
        record = self.session.get(UserRecord, str(user_id))
        return to_user(record) if record is not None else None

    def set_active(self, user_id: UUID, active: bool) -> User:
        record = self.session.get(UserRecord, str(user_id))
        if record is None:
            raise UserNotFoundError("User not found")
        record.is_active = active
        self.session.commit()
        return to_user(record)

    def change_password(self, user_id: UUID, expected_hash: str, new_hash: str) -> bool:
        result = self.session.execute(
            update(UserRecord)
            .where(
                UserRecord.id == str(user_id),
                UserRecord.password_hash == expected_hash,
                UserRecord.is_active.is_(True),
            )
            .values(password_hash=new_hash)
            .returning(UserRecord.id)
        ).scalar_one_or_none()
        self.session.commit()
        return result is not None
