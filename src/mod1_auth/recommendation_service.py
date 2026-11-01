"""Auditable, human-reviewed anomaly proposals; approval never grants/revokes access."""

import hashlib
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from mod1_auth.identity_service import IdentityError, IdentityService, iso, page, timestamp


class RecommendationService:
    def __init__(
        self, identity: IdentityService, generate: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> None:
        self.identity = identity
        self.store = identity.store
        self.generate = generate

    def context(self) -> dict[str, Any]:
        events = [
            e for e in self.store.items("audit") if not e["action"].startswith("recommendation.")
        ][:200]
        user_ids = {e.get("actor_id") for e in events} | {e.get("target_id") for e in events}
        users = [
            {"id": str(u.id), "is_active": u.is_active}
            for u in self.identity.users.identity.all_users()
            if str(u.id) in user_ids
        ]
        return {"audit_events": events, "users": sorted(users, key=lambda u: u["id"])}

    @staticmethod
    def version(context: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()

    def list(self, token: str, limit: int, offset: int) -> dict[str, Any]:
        self.identity.admin(token)
        return page(self.store.items("recommendation"), limit, offset)

    def get(self, token: str, rid: UUID) -> dict[str, Any]:
        self.identity.admin(token)
        result = self.store.get("recommendation:" + str(rid))
        if not result:
            raise IdentityError(404, "Recommendation unavailable")
        return result

    def create(self, token: str) -> dict[str, Any]:
        admin = self.identity.admin(token)
        context = self.context()
        # Release the read transaction during provider I/O; recheck under the mutex.
        self.store.end_read()
        output = self.generate(context)
        allowed_evidence = {e["id"] for e in context["audit_events"]}
        allowed_users = {u["id"] for u in context["users"]}
        if any(e not in allowed_evidence for e in output["evidence"]):
            raise IdentityError(503, "Recommendation provider unavailable")
        for suggestion in output["suggestions"]:
            if suggestion["user_id"] not in allowed_users or any(
                e not in allowed_evidence for e in suggestion["evidence_ids"]
            ):
                raise IdentityError(503, "Recommendation provider unavailable")
        now = timestamp()
        record = dict(
            output,
            id=str(uuid4()),
            kind="access_anomalies",
            status="pending",
            version=1,
            created_at=iso(now),
            expires_at=iso(now + 86400),
            context_version=self.version(context),
            model=self.identity.settings.ai_model,
            provider="structured-http",
            simulated=self.identity.settings.ai_simulated,
        )
        with self.store.atomic():
            self.identity.admin(token)
            if self.version(self.context()) != record["context_version"]:
                raise IdentityError(409, "Audit context changed; request a new recommendation")
            self.store.put(
                "recommendation:" + record["id"], "recommendation", str(admin.id), record
            )
            self.store.audit(str(admin.id), None, "recommendation.created")
        return record

    def decide(self, token: str, rid: UUID, expected: int, approve: bool) -> dict[str, Any]:
        stale = False
        with self.store.atomic():
            admin = self.identity.admin(token)
            record = self.get(token, rid)
            if record["version"] != expected or record["status"] != "pending":
                raise IdentityError(409, "Recommendation decision conflicts")
            stale = record["context_version"] != self.version(self.context())
            from datetime import datetime

            stale = stale or datetime.fromisoformat(record["expires_at"]).timestamp() <= timestamp()
            record["status"] = "expired" if stale else ("approved" if approve else "rejected")
            record["version"] += 1
            self.store.put("recommendation:" + str(rid), "recommendation", str(admin.id), record)
            self.store.audit(str(admin.id), None, "recommendation." + record["status"])
        if stale:
            raise IdentityError(409, "Audit context changed; request a new recommendation")
        return record
