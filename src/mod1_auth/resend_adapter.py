"""Resend transactional HTTP transport. No database, retries or secret logging."""

import hashlib
import json
from typing import Any
from uuid import UUID

import httpx


class ResendUnavailable(Exception):
    pass


class ResendAdapter:
    def __init__(
        self, *, api_key: str, sender: str, timeout: float, client: httpx.Client | None = None
    ) -> None:
        self.api_key, self.sender, self.timeout, self.client = api_key, sender, timeout, client

    def send(self, recipient: str, subject: str, body: str) -> None:
        payload = {"from": self.sender, "to": [recipient], "subject": subject, "text": body}
        identity = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "mod1-auth/0.3.0",
            "Idempotency-Key": "identity-mail/" + identity,
        }
        try:
            if self.client is not None:
                self.request(self.client, payload, headers)
            else:
                with httpx.Client(
                    timeout=self.timeout, trust_env=False, follow_redirects=False
                ) as client:
                    self.request(client, payload, headers)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise ResendUnavailable("Mail delivery unavailable") from None

    def request(
        self, client: httpx.Client, payload: dict[str, Any], headers: dict[str, str]
    ) -> None:
        with client.stream(
            "POST",
            "https://api.resend.com/emails",
            json=payload,
            headers=headers,
            timeout=self.timeout,
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise ResendUnavailable("Mail delivery unavailable")
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 16384:
                    raise ResendUnavailable("Mail delivery unavailable")
            receipt = json.loads(data)
            if not isinstance(receipt, dict) or not isinstance(receipt.get("id"), str):
                raise ResendUnavailable("Mail delivery unavailable")
            UUID(receipt["id"])
