"""Explicit SMTP transport or isolated local mailbox; no implicit deliveries."""

import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from uuid import uuid4

import httpx

from mod1_auth.config import Settings
from mod1_auth.identity_repository import IdentityRepository
from mod1_auth.resend_adapter import ResendAdapter, ResendUnavailable


class MailUnavailable(Exception):
    pass


class MailAdapter:
    def __init__(
        self,
        settings: Settings,
        store: IdentityRepository,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.http_client = http_client

    def provider(self) -> str:
        selected = self.settings.mail_provider
        if selected == "auto":
            if self.settings.local_mailbox_enabled:
                selected = "local"
            elif self.settings.resend_api_key or self.settings.resend_from:
                selected = "resend"
            elif self.settings.smtp_host:
                selected = "smtp"
        if (
            (selected == "local" and self.settings.local_mailbox_enabled)
            or (selected == "resend" and self.settings.resend_api_key and self.settings.resend_from)
            or (selected == "smtp" and self.settings.smtp_host)
        ):
            return selected
        raise MailUnavailable("Mail delivery unavailable")

    def require_configured(self) -> None:
        self.provider()

    def send(self, recipient: str, subject: str, body: str) -> None:
        provider = self.provider()
        if provider == "resend":
            assert self.settings.resend_api_key and self.settings.resend_from
            try:
                ResendAdapter(
                    api_key=self.settings.resend_api_key.get_secret_value(),
                    sender=self.settings.resend_from,
                    timeout=self.settings.resend_timeout_seconds,
                    client=self.http_client,
                ).send(recipient, subject, body)
            except ResendUnavailable:
                raise MailUnavailable("Mail delivery unavailable") from None
            return
        if provider == "local":
            message_id = str(uuid4())
            self.store.put(
                "mail:" + message_id,
                "mail",
                recipient,
                {
                    "id": message_id,
                    "to": recipient,
                    "subject": subject,
                    "body": body,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            return
        message = EmailMessage()
        message["From"] = self.settings.smtp_from
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        try:
            assert self.settings.smtp_host is not None
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=5) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                if self.settings.smtp_username and self.settings.smtp_password:
                    smtp.login(
                        self.settings.smtp_username, self.settings.smtp_password.get_secret_value()
                    )
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailUnavailable() from exc
