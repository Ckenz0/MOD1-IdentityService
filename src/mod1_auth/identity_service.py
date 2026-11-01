"""Identity use cases: session lifetime, lockout, administration and audit."""

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel

from mod1_auth.domain import InvalidCredentialsError, User
from mod1_auth.repositories import UserRepository
from mod1_auth.security import TokenResponse, TokenService, TokenValidationError, verify_password


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def timestamp() -> float:
    return datetime.now(UTC).timestamp()


def iso(value: float | None) -> str | None:
    return (
        datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")
        if value is not None
        else None
    )


def page(items: list[Any], limit: int, offset: int) -> dict[str, Any]:
    return {
        "items": items[offset : offset + limit],
        "total": len(items),
        "limit": limit,
        "offset": offset,
    }


class IdentityError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


class MFAChallenge(BaseModel):
    mfa_required: bool = True
    challenge_token: str
    expires_in: int = 300


class IdentityService:
    def __init__(self, users: UserRepository, tokens: TokenService) -> None:
        self.users = users
        self.store = users.identity
        self.tokens = tokens
        self.settings = tokens.settings

    def flags(self, user: User) -> dict[str, Any]:
        account = self.store.account(user.id)
        return {
            "is_admin": bool(account["is_admin"]),
            "email_verified": bool(account["email_verified"]),
        }

    def current(self, token: str) -> User:
        try:
            claims = self.tokens.verify(token)
        except TokenValidationError as exc:
            raise InvalidCredentialsError() from exc
        user = self.users.get_by_id(claims.sub)
        if not user or not user.is_active:
            raise InvalidCredentialsError()
        account = self.store.account(user.id)
        if not claims.sid and claims.iat <= account["revoked_before"]:
            raise InvalidCredentialsError()
        if self.store.get("jti:" + str(claims.jti)):
            raise InvalidCredentialsError()
        if claims.sid:
            state = self.store.get("session:" + str(claims.sid))
            self.require_session(state, str(user.id))
            if state and state["created"] <= account["revoked_before"]:
                raise InvalidCredentialsError()
        return user

    @staticmethod
    def require_session(state: dict[str, Any] | None, user_id: str) -> None:
        now = timestamp()
        if (
            not state
            or state["user_id"] != user_id
            or state.get("revoked_at")
            or now >= state["idle"]
            or now >= state["absolute"]
        ):
            raise InvalidCredentialsError()

    def admin(self, token: str) -> User:
        user = self.current(token)
        if not self.store.account(user.id)["is_admin"]:
            raise IdentityError(403, "Action denied")
        return user

    def login(self, email: str, password: str, dummy_hash: str) -> TokenResponse | MFAChallenge:
        normalized = email.strip().lower()
        # Hashing remains uniform for unknown, inactive and locked accounts.
        user = self.users.get_by_email(normalized)
        verified_hash = user.password_hash if user else dummy_hash
        valid = verify_password(password, verified_hash)
        result: TokenResponse | MFAChallenge | None
        with self.store.atomic():
            # Reload mutable account state after the serialization lock.
            user = self.users.get_by_email(normalized)
            # A committed reset/change invalidates an earlier expensive check.
            # Reject this attempt rather than issue a new post-revocation session.
            valid = valid and user is not None and user.password_hash == verified_hash
            now = timestamp()
            key = "login:" + digest(normalized)
            state = self.store.get(key) or {"failures": [], "locked_until": 0}
            failures = [
                v for v in state["failures"] if v > now - self.settings.login_window_minutes * 60
            ]
            locked = state["locked_until"] > now
            if not user or not user.is_active or not valid or locked:
                if not locked:
                    failures.append(now)
                    state["failures"] = failures
                    if len(failures) >= self.settings.login_max_failures:
                        state["locked_until"] = now + self.settings.login_lock_minutes * 60
                self.store.put(key, "login", str(user.id) if user else "", state)
                self.store.audit(None, str(user.id) if user else None, "login", "denied")
                result = None
            else:
                if self.store.account(user.id)["mfa_enabled"]:
                    opaque = secrets.token_urlsafe(48)
                    self.store.put(
                        "challenge:" + digest(opaque),
                        "challenge",
                        str(user.id),
                        {
                            "user_id": str(user.id),
                            "expires": now + 300,
                            "used": False,
                            "attempts": 0,
                        },
                    )
                    result = MFAChallenge(challenge_token=opaque)
                else:
                    self.store.put(key, "login", str(user.id), {"failures": [], "locked_until": 0})
                    result = self.new_session(user)
                self.store.audit(str(user.id), str(user.id), "login")
        if result is None:
            raise InvalidCredentialsError()
        return result

    def new_session(self, user: User) -> TokenResponse:
        now = timestamp()
        state = {
            "id": str(uuid4()),
            "user_id": str(user.id),
            "created": now,
            "last_activity": now,
            "idle": now + self.settings.session_idle_minutes * 60,
            "absolute": now + self.settings.session_max_hours * 3600,
            "revoked_at": None,
            "client_label": "Browser/API",
        }
        return self.issue_session(user, state)

    def issue_session(self, user: User, state: dict[str, Any]) -> TokenResponse:
        refresh = secrets.token_urlsafe(48)
        self.store.put(
            "refresh:" + digest(refresh),
            "refresh",
            str(user.id),
            {"session_id": state["id"], "user_id": str(user.id), "used": False},
        )
        self.store.put("session:" + state["id"], "session", str(user.id), state)
        token = self.tokens.issue(user.id, session_id=UUID(state["id"]))
        return token.model_copy(
            update={
                "refresh_token": refresh,
                "session_id": UUID(state["id"]),
                "idle_expires_at": datetime.fromtimestamp(state["idle"], UTC),
                "absolute_expires_at": datetime.fromtimestamp(state["absolute"], UTC),
            }
        )

    def refresh(self, refresh_token: str) -> TokenResponse:
        result = None
        with self.store.atomic():
            record = self.store.get("refresh:" + digest(refresh_token))
            if record:
                state = self.store.get("session:" + record["session_id"])
                if record["used"]:
                    if state:
                        state["revoked_at"] = timestamp()
                        self.store.put(
                            "session:" + state["id"], "session", record["user_id"], state
                        )
                    self.store.audit(
                        record["user_id"], record["user_id"], "refresh_replay", "denied"
                    )
                else:
                    user = self.users.get_by_id(UUID(record["user_id"]))
                    try:
                        self.require_session(state, record["user_id"])
                    except InvalidCredentialsError:
                        state = None
                    if state and user and user.is_active:
                        record["used"] = True
                        self.store.put(
                            "refresh:" + digest(refresh_token), "refresh", record["user_id"], record
                        )
                        result = self.issue_session(user, state)
        if result is None:
            raise InvalidCredentialsError()
        return result

    def list_sessions(self, token: str, limit: int, offset: int) -> dict[str, Any]:
        user = self.current(token)
        sid = self.tokens.verify(token).sid
        items = [
            {
                "id": s["id"],
                "created_at": iso(s["created"]),
                "last_activity_at": iso(s["last_activity"]),
                "idle_expires_at": iso(s["idle"]),
                "absolute_expires_at": iso(s["absolute"]),
                "revoked_at": iso(s["revoked_at"]),
                "client_label": s["client_label"],
                "is_current": s["id"] == str(sid),
            }
            for s in self.store.items("session", str(user.id))
        ]
        return page(items, limit, offset)

    def logout(self, token: str) -> None:
        # A repeated logout of the same signed session has no further effect.
        try:
            claims = self.tokens.verify(token)
        except TokenValidationError as exc:
            raise InvalidCredentialsError() from exc
        with self.store.atomic():
            user = self.users.get_by_id(claims.sub)
            state = self.store.get("session:" + str(claims.sid))
            if not user or not user.is_active or not state or state["user_id"] != str(user.id):
                raise InvalidCredentialsError()
            if not state["revoked_at"]:
                state["revoked_at"] = timestamp()
                self.store.put("session:" + state["id"], "session", str(user.id), state)
                self.store.audit(str(user.id), str(user.id), "logout")

    def activity(self, token: str) -> dict[str, Any]:
        with self.store.atomic():
            user = self.current(token)
            sid = self.tokens.verify(token).sid
            state = self.store.get("session:" + str(sid))
            self.require_session(state, str(user.id))
            assert state is not None
            now = timestamp()
            state["last_activity"] = now
            state["idle"] = min(now + self.settings.session_idle_minutes * 60, state["absolute"])
            self.store.put("session:" + str(sid), "session", str(user.id), state)
            return {
                "idle_expires_at": iso(state["idle"]),
                "absolute_expires_at": iso(state["absolute"]),
            }

    def revoke(self, token: str, sid: UUID | None = None, *, all_sessions: bool = False) -> None:
        with self.store.atomic():
            user = self.current(token)
            if all_sessions:
                self.store.revoke_all(user.id)
            else:
                sid = sid or self.tokens.verify(token).sid
                state = self.store.get("session:" + str(sid))
                if not state or state["user_id"] != str(user.id):
                    raise IdentityError(404, "Session unavailable")
                state["revoked_at"] = timestamp()
                self.store.put("session:" + str(sid), "session", str(user.id), state)
            self.store.audit(str(user.id), str(user.id), "sessions_revoked")

    def audit(self, token: str, limit: int, offset: int, *, admin: bool = False) -> dict[str, Any]:
        user = self.admin(token) if admin else self.current(token)
        return page(self.store.items("audit", None if admin else str(user.id)), limit, offset)

    def list_users(self, token: str, q: str, limit: int, offset: int) -> dict[str, Any]:
        self.admin(token)
        users = [
            u
            for u in self.store.all_users()
            if q.casefold() in (u.display_name + " " + u.email).casefold()
        ]
        return page([self.user_view(u) for u in users], limit, offset)

    def user_view(self, user: User) -> dict[str, Any]:
        return {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat(),
            **self.flags(user),
        }

    def admin_action(
        self, token: str, target: UUID, action: str, active: bool | None = None
    ) -> dict[str, Any]:
        with self.store.atomic():
            actor = self.admin(token)
            user = self.users.get_by_id(target)
            if not user:
                raise IdentityError(404, "User unavailable")
            if action == "unlock":
                self.store.put(
                    "login:" + digest(user.email),
                    "login",
                    str(target),
                    {"failures": [], "locked_until": 0},
                )
                account = self.store.account(target)
                account["factor_failures"] = []
                account["factor_locked_until"] = 0
                self.store.save_account(target, account)
            elif action == "revoke":
                self.store.revoke_all(target)
            elif action == "active":
                # Repository mutation participates in the enclosing security transaction.
                self.users.update_active(target, bool(active))
                if not active:
                    self.store.revoke_all(target)
            self.store.audit(str(actor.id), str(target), "admin_" + action)
            updated = self.users.get_by_id(target)
            assert updated is not None
            return self.user_view(updated)

    def revoke_jti(self, token: str, jti: UUID) -> None:
        with self.store.atomic():
            actor = self.admin(token)
            self.store.put("jti:" + str(jti), "jti", str(actor.id), {"revoked": True})
            self.store.audit(str(actor.id), None, "token_revoked")

    def user_status(self, token: str, user_id: UUID) -> dict[str, Any]:
        self.current(token)
        user = self.users.get_by_id(user_id)
        if not user:
            raise IdentityError(404, "User unavailable")
        return {"id": str(user.id), "is_active": user.is_active}
