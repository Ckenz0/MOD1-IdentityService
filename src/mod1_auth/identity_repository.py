"""Identity security persistence. Transactions serialize on a durable database mutex.

The mutex is intentionally conservative: security mutations are short, and both
SQLite and PostgreSQL must give refresh/recovery tokens single-use semantics.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Float, String, select, text, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from mod1_auth.database import Base


class SecurityDocument(Base):
    __tablename__ = "security_documents"
    __table_args__ = {"schema": "mod1_identity"}
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    owner: Mapped[str] = mapped_column(String(320), index=True)
    created: Mapped[float] = mapped_column(Float)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class SecurityMutex(Base):
    __tablename__ = "security_mutex"
    __table_args__ = {"schema": "mod1_identity"}
    id: Mapped[int] = mapped_column(primary_key=True)
    generation: Mapped[int] = mapped_column(default=0)


class IdentityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @contextmanager
    def atomic(self) -> Iterator[None]:
        # Discard only read transactions; callers enter before making mutations.
        self.session.rollback()
        if self.session.get_bind().dialect.name == "sqlite":
            self.session.execute(text("BEGIN IMMEDIATE"))
        else:
            self.session.execute(
                update(SecurityMutex)
                .where(SecurityMutex.id == 1)
                .values(generation=SecurityMutex.generation + 1)
            )
        try:
            yield
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def get(self, key: str) -> dict[str, Any] | None:
        row = self.session.get(SecurityDocument, key, populate_existing=True)
        return dict(row.data) if row else None

    def end_read(self) -> None:
        self.session.rollback()

    def put(self, key: str, kind: str, owner: str, data: dict[str, Any]) -> None:
        row = self.session.get(SecurityDocument, key)
        if row is None:
            row = SecurityDocument(
                key=key,
                kind=kind,
                owner=owner,
                created=datetime.now(UTC).timestamp(),
                data=dict(data),
            )
            self.session.add(row)
        else:
            row.data = dict(data)
        self.session.flush()

    def items(self, kind: str, owner: str | None = None) -> list[dict[str, Any]]:
        query = select(SecurityDocument).where(SecurityDocument.kind == kind)
        if owner is not None:
            query = query.where(SecurityDocument.owner == owner)
        rows = self.session.scalars(query.order_by(SecurityDocument.created.desc())).all()
        return [dict(row.data) for row in rows]

    def account(self, user_id: UUID | str) -> dict[str, Any]:
        return {
            "is_admin": False,
            "email_verified": False,
            "revoked_before": 0,
            "mfa_enabled": False,
        } | (self.get("account:" + str(user_id)) or {})

    def save_account(self, user_id: UUID | str, data: dict[str, Any]) -> None:
        self.put("account:" + str(user_id), "account", str(user_id), data)

    def audit(
        self, actor: str | None, target: str | None, action: str, outcome: str = "success"
    ) -> None:
        event_id = str(uuid4())
        self.put(
            "audit:" + event_id,
            "audit",
            target or "",
            {
                "id": event_id,
                "actor_id": actor,
                "target_id": target,
                "action": action,
                "outcome": outcome,
                "origin": "identity",
                "created_at": datetime.now(UTC).isoformat(),
            },
        )

    def revoke_all(self, user_id: UUID | str) -> None:
        now = datetime.now(UTC).timestamp()
        account = self.account(user_id)
        account["revoked_before"] = now
        self.save_account(user_id, account)
        for item in self.items("session", str(user_id)):
            item["revoked_at"] = now
            self.put("session:" + item["id"], "session", str(user_id), item)

    def replace_password(self, user_id: str, new_hash: str) -> None:
        from mod1_auth.repositories import UserRecord

        self.session.execute(
            update(UserRecord).where(UserRecord.id == user_id).values(password_hash=new_hash)
        )

    def all_users(self) -> list[Any]:
        from mod1_auth.repositories import UserRecord, to_user

        return [to_user(row) for row in self.session.scalars(select(UserRecord)).all()]
