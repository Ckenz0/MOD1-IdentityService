"""Bounded structured HTTP adapter, disabled unless explicitly configured."""

from typing import Any

import httpx

from mod1_auth.config import Settings
from mod1_auth.identity_service import IdentityError
from mod1_auth.recommendations import AnomalyResponse


class AIAdapter:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.ai_base_url:
            raise IdentityError(503, "Recommendation provider unavailable")
        headers = {"Accept": "application/json"}
        if self.settings.ai_api_key:
            headers["Authorization"] = "Bearer " + self.settings.ai_api_key.get_secret_value()
        try:
            with httpx.Client(
                transport=self.transport, timeout=20, follow_redirects=False, trust_env=False
            ) as client:
                with client.stream(
                    "POST",
                    self.settings.ai_base_url,
                    headers=headers,
                    json={
                        "schema_version": 1,
                        "kind": "access_anomalies",
                        "context": context,
                        "model": self.settings.ai_model,
                    },
                ) as response:
                    response.raise_for_status()
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 262144:
                            raise ValueError("Provider response exceeds bound")
                    return AnomalyResponse.model_validate_json(content).model_dump(mode="json")
        except (httpx.HTTPError, ValueError, TypeError):
            raise IdentityError(503, "Recommendation provider unavailable") from None
