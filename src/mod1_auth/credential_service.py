"""Recovery, ownership verification and MFA application policies."""

import hmac
import secrets
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

from email_validator import validate_email

from mod1_auth.credential_crypto import CredentialKeyError, create_seed, totp_step
from mod1_auth.domain import InvalidCredentialsError, User
from mod1_auth.identity_service import IdentityError, IdentityService, digest, page, timestamp
from mod1_auth.mail_adapter import MailAdapter, MailUnavailable
from mod1_auth.security import TokenResponse, hash_password, verify_password


class MailDeliveryError(IdentityError):
    def __init__(self) -> None:
        super().__init__(503, "Mail delivery unavailable")


class CredentialService:
    def __init__(self, identity: IdentityService) -> None:
        self.identity = identity
        self.store = identity.store
        self.settings = identity.settings
        self.mail = MailAdapter(self.settings, self.store)

    def require_mail(self) -> None:
        try:
            self.mail.require_configured()
        except MailUnavailable as exc:
            raise IdentityError(503, "Mail delivery unavailable") from exc

    def request_reset(self, email: str) -> None:
        self.require_mail()
        normalized = email.strip().lower()
        try:
            with self.store.atomic():
                user = self.identity.users.get_by_email(normalized)
                if user and user.is_active:
                    self.send_token(str(user.id), user.email, "reset", 1800)
        except MailDeliveryError:
            # A configured provider's outage must not distinguish existing
            # accounts. The failed credential transaction is already rolled back.
            with self.store.atomic():
                self.store.audit(None, None, "password_reset_delivery_failed", "failure")
                if user:
                    key = "mail-rate:reset:" + str(user.id)
                    previous = self.store.get(key) or {"sent": []}
                    now = timestamp()
                    attempts = [value for value in previous["sent"] if value > now - 900]
                    self.store.put(key, "mail-rate", str(user.id), {"sent": attempts + [now]})

    def request_email(self, token: str) -> None:
        self.require_mail()
        with self.store.atomic():
            user = self.identity.current(token)
            if not self.store.account(user.id)["email_verified"]:
                self.send_token(str(user.id), user.email, "verify", 86400)

    def send_token(self, user_id: str, email: str, purpose: str, ttl: int) -> None:
        now = timestamp()
        rate_key = "mail-rate:" + purpose + ":" + user_id
        state = self.store.get(rate_key) or {"sent": []}
        sent = [value for value in state["sent"] if value > now - 900]
        if len(sent) >= 3 or (sent and sent[-1] > now - 60):
            return
        opaque = secrets.token_urlsafe(48)
        self.store.put(
            "credential:" + digest(opaque),
            "credential",
            user_id,
            {
                "user_id": user_id,
                "purpose": purpose,
                "expires": now + ttl,
                "used": False,
                "attempts": 0,
            },
        )
        fragment = "verify-email" if purpose == "verify" else "recovery"
        link = self.settings.frontend_origin + "/#" + fragment + "=" + opaque
        try:
            self.mail.send(
                email, "Verify email" if purpose == "verify" else "Set your password", link
            )
        except MailUnavailable as exc:
            raise MailDeliveryError() from exc
        self.store.put(rate_key, "mail-rate", user_id, {"sent": sent + [now]})
        self.store.audit(user_id, user_id, purpose + "_requested")

    def require_credential(self, opaque: str, purpose: str) -> dict[str, Any] | None:
        record = self.store.get("credential:" + digest(opaque))
        if (
            not record
            or record["purpose"] != purpose
            or record["used"]
            or record["expires"] <= timestamp()
            or record["attempts"] >= 5
        ):
            return None
        user = self.identity.users.get_by_id(UUID(record["user_id"]))
        return record if user and user.is_active else None

    def confirm_email(self, opaque: str) -> None:
        with self.store.atomic():
            record = self.require_credential(opaque, "verify")
            if not record:
                raise IdentityError(400, "Verification rejected")
            account = self.store.account(record["user_id"])
            account["email_verified"] = True
            self.store.save_account(record["user_id"], account)
            record["used"] = True
            self.store.put("credential:" + digest(opaque), "credential", record["user_id"], record)
            self.store.audit(record["user_id"], record["user_id"], "email_verified")

    def confirm_reset(
        self, opaque: str, password: str, code: str | None, recovery: str | None
    ) -> None:
        if not self.settings.password_min_length <= len(password) <= 128:
            raise IdentityError(422, "Password does not meet the configured length policy")
        new_hash = hash_password(password)
        accepted = False
        with self.store.atomic():
            record = self.require_credential(opaque, "reset")
            if record:
                account = self.store.account(record["user_id"])
                factor_ok = not account["mfa_enabled"] or self.factor(account, code, recovery)
                self.store.save_account(record["user_id"], account)
                record["attempts"] += 1
                if factor_ok:
                    self.store.replace_password(record["user_id"], new_hash)
                    self.store.save_account(record["user_id"], account)
                    self.store.revoke_all(record["user_id"])
                    record["used"] = True
                    accepted = True
                    self.store.audit(record["user_id"], record["user_id"], "password_reset")
                self.store.put(
                    "credential:" + digest(opaque), "credential", record["user_id"], record
                )
        if not accepted:
            raise IdentityError(400, "Password reset rejected")

    def factor(self, account: dict[str, Any], code: str | None, recovery: str | None) -> bool:
        now = timestamp()
        if account.get("factor_locked_until", 0) > now:
            return False
        valid = self.verify_factor(account, code, recovery)
        if valid:
            account["factor_failures"] = []
            account["factor_locked_until"] = 0
        else:
            failures = [
                value
                for value in account.get("factor_failures", [])
                if value > now - self.settings.login_window_minutes * 60
            ] + [now]
            account["factor_failures"] = failures
            if len(failures) >= self.settings.login_max_failures:
                account["factor_locked_until"] = now + self.settings.login_lock_minutes * 60
        return valid

    def verify_factor(
        self, account: dict[str, Any], code: str | None, recovery: str | None
    ) -> bool:
        if bool(code) == bool(recovery):
            return False
        if recovery:
            hashed = digest(recovery)
            codes = account.get("recovery_hashes", [])
            for item in codes:
                if hmac.compare_digest(item, hashed):
                    account["recovery_hashes"] = [value for value in codes if value != item]
                    return True
            return False
        try:
            step = totp_step(
                self.settings,
                account.get("mfa_seed", ""),
                code or "",
                timestamp(),
                account.get("last_step", -1),
            )
        except CredentialKeyError as exc:
            raise IdentityError(503, "MFA configuration unavailable") from exc
        if step is None:
            return False
        account["last_step"] = step
        return True

    def mfa_state(self, token: str) -> dict[str, bool]:
        user = self.identity.current(token)
        return {"enabled": bool(self.store.account(user.id)["mfa_enabled"])}

    def setup(self, token: str, password: str) -> dict[str, str]:
        with self.store.atomic():
            user = self.identity.current(token)
            if not verify_password(password, user.password_hash):
                raise IdentityError(400, "MFA setup rejected")
            account = self.store.account(user.id)
            if account["mfa_enabled"]:
                raise IdentityError(409, "MFA already enabled")
            try:
                secret, encrypted = create_seed(self.settings)
            except CredentialKeyError as exc:
                raise IdentityError(503, "MFA configuration unavailable") from exc
            account["pending_seed"] = encrypted
            account["pending_expires"] = timestamp() + 600
            self.store.save_account(user.id, account)
            issuer = quote(self.settings.jwt_issuer, safe="")
            label = quote(self.settings.jwt_issuer + ":" + user.email, safe="")
            return {
                "secret": secret,
                "provisioning_uri": f"otpauth://totp/{label}?secret={secret}&issuer={issuer}"
                "&algorithm=SHA1&digits=6&period=30",
            }

    @staticmethod
    def recovery_codes(account: dict[str, Any]) -> list[str]:
        codes = [secrets.token_urlsafe(16) for _ in range(10)]
        account["recovery_hashes"] = [digest(code) for code in codes]
        return codes

    def enable(self, token: str, code: str) -> dict[str, list[str]]:
        codes: list[str] | None = None
        with self.store.atomic():
            user = self.identity.current(token)
            account = self.store.account(user.id)
            if (
                account["mfa_enabled"]
                or not account.get("pending_seed")
                or account.get("pending_expires", 0) <= timestamp()
            ):
                raise IdentityError(400, "MFA activation rejected")
            candidate = dict(account) | {"mfa_seed": account["pending_seed"], "last_step": -1}
            if self.factor(candidate, code, None):
                candidate.pop("pending_seed", None)
                candidate.pop("pending_expires", None)
                candidate["mfa_enabled"] = True
                codes = self.recovery_codes(candidate)
                self.store.audit(str(user.id), str(user.id), "mfa_enabled")
            self.store.save_account(user.id, candidate)
        if codes is None:
            raise IdentityError(400, "MFA activation rejected")
        return {"recovery_codes": codes}

    def verify_challenge(
        self, opaque: str, code: str | None, recovery: str | None
    ) -> TokenResponse:
        result = None
        with self.store.atomic():
            state = self.store.get("challenge:" + digest(opaque))
            if (
                state
                and not state["used"]
                and state["expires"] > timestamp()
                and state["attempts"] < 5
            ):
                user_id = state["user_id"]
                user = self.identity.users.get_by_id(UUID(user_id))
                account = self.store.account(user_id)
                if (
                    user
                    and user.is_active
                    and account["mfa_enabled"]
                    and state["expires"] - 300 > account["revoked_before"]
                ):
                    state["attempts"] += 1
                    login_key = "login:" + digest(user.email)
                    login = self.store.get(login_key) or {"failures": [], "locked_until": 0}
                    if login["locked_until"] <= timestamp() and self.factor(
                        account, code, recovery
                    ):
                        self.store.save_account(user_id, account)
                        state["used"] = True
                        result = self.identity.new_session(user)
                        self.store.audit(user_id, user_id, "mfa_login")
                        self.store.put(
                            login_key, "login", user_id, {"failures": [], "locked_until": 0}
                        )
                    else:
                        now = timestamp()
                        failures = [
                            v
                            for v in login["failures"]
                            if v > now - self.settings.login_window_minutes * 60
                        ] + [now]
                        login["failures"] = failures
                        if len(failures) >= self.settings.login_max_failures:
                            login["locked_until"] = now + self.settings.login_lock_minutes * 60
                        self.store.put(login_key, "login", user_id, login)
                        self.store.audit(user_id, user_id, "mfa_login", "denied")
                    self.store.save_account(user_id, account)
                    self.store.put("challenge:" + digest(opaque), "challenge", user_id, state)
        if result is None:
            raise InvalidCredentialsError()
        return result

    def manage(
        self,
        token: str,
        password: str,
        code: str | None,
        recovery: str | None,
        *,
        disable: bool = False,
    ) -> dict[str, list[str]]:
        accepted = False
        codes: list[str] = []
        with self.store.atomic():
            user = self.identity.current(token)
            account = self.store.account(user.id)
            if (
                account["mfa_enabled"]
                and verify_password(password, user.password_hash)
                and self.factor(account, code, recovery)
            ):
                if disable:
                    account["mfa_enabled"] = False
                    account.pop("mfa_seed", None)
                    account.pop("recovery_hashes", None)
                    account.pop("last_step", None)
                else:
                    codes = self.recovery_codes(account)
                self.store.save_account(user.id, account)
                self.store.audit(
                    str(user.id),
                    str(user.id),
                    "mfa_disabled" if disable else "mfa_recovery_regenerated",
                )
                accepted = True
            self.store.save_account(user.id, account)
        if not accepted:
            raise IdentityError(400, "MFA operation rejected")
        return {"recovery_codes": codes}

    def mailbox(self, token: str, limit: int, offset: int) -> dict[str, Any]:
        if not self.settings.local_mailbox_enabled:
            raise IdentityError(404, "Resource unavailable")
        self.identity.admin(token)
        return page(self.store.items("mail"), limit, offset)

    def provision(self, token: str, email: str, name: str) -> None:
        self.identity.admin(token)
        self.require_mail()
        email = email.strip().lower()
        try:
            validate_email(email, check_deliverability=False)
        except ValueError as exc:
            raise IdentityError(422, "Invalid account data") from exc
        if not 1 <= len(name.strip()) <= 120:
            raise IdentityError(422, "Invalid account data")
        password_hash = hash_password(secrets.token_urlsafe(64))
        with self.store.atomic():
            actor = self.identity.admin(token)
            user = self.identity.users.get_by_email(email)
            if user is None:
                user = self.identity.users.add(
                    User(uuid4(), email, name.strip(), password_hash, True, datetime.now(UTC)),
                    commit=False,
                )
            if user.is_active:
                self.send_token(str(user.id), email, "reset", 1800)
            self.store.audit(str(actor.id), str(user.id), "account_provisioned")
