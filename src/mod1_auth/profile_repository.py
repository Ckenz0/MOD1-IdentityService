from typing import Any
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, String, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from mod1_auth.database import Base
from mod1_auth.domain import InvalidCredentialsError
from mod1_auth.profiles import Profile, ProfilePatch
from mod1_auth.repositories import UserRecord


class ProfileRecord(Base):
    __tablename__ = "profiles"
    __table_args__ = {"schema": "mod1_identity"}

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mod1_identity.users.id"), primary_key=True
    )
    summary: Mapped[str] = mapped_column(String(2000), nullable=False)
    seniority: Mapped[str] = mapped_column(String(20), nullable=False)
    weekly_availability_hours: Mapped[int] = mapped_column(nullable=False)
    skills: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)


class ProfileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: UUID) -> Profile:
        record = self.session.get(ProfileRecord, str(user_id))
        if record is None:
            return Profile(user_id=user_id)
        return Profile.model_validate(record, from_attributes=True)

    def patch(self, user_id: UUID, patch: ProfilePatch) -> Profile:
        changes = patch.model_dump(mode="json", exclude_unset=True)
        values = Profile(user_id=user_id).model_dump(mode="json") | changes
        dialect = self.session.get_bind().dialect.name
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        # INSERT ... SELECT rechecks the active account in the same SQL statement.
        # Conflict updates only supplied columns, preserving concurrent partial edits.
        statement = insert(ProfileRecord).from_select(
            list(values),
            select(
                *[
                    literal(value, type_=ProfileRecord.__table__.c[key].type)
                    for key, value in values.items()
                ]
            ).where(UserRecord.id == str(user_id), UserRecord.is_active.is_(True)),
        )
        returning = statement.on_conflict_do_update(
            index_elements=[ProfileRecord.user_id],
            set_={key: getattr(statement.excluded, key) for key in changes},
        ).returning(ProfileRecord)
        try:
            record = self.session.scalars(
                returning, execution_options={"populate_existing": True}
            ).one_or_none()
            if record is None:
                raise InvalidCredentialsError()
            profile = Profile.model_validate(record, from_attributes=True)
            self.session.commit()
            return profile
        except (SQLAlchemyError, InvalidCredentialsError):
            self.session.rollback()
            raise
