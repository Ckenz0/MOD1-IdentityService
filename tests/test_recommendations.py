import json
from uuid import uuid4

import httpx
import pytest
from test_recovery_mfa import promote
from test_sessions import bearer, login


@pytest.mark.parametrize("provider", ["structured-http", "gemini"])
def test_empty_proposal_can_be_rejected_but_cannot_be_approved(
    client, user, engine, settings, provider
):
    from mod1_auth.ai_adapter import AIAdapter
    from mod1_auth.dependencies import get_ai_adapter

    promote(engine, user)
    headers = bearer(login(client, user).json())
    # Construct validated configuration; do not read any local env file.
    configured = type(settings)(
        **(
            settings.model_dump()
            | {
                "ai_provider": provider,
                "ai_base_url": "http://127.0.0.1:9765",
                "gemini_api_key": "test-only-key",
                "gemini_model": "gemini-3.5-flash-lite",
            }
        ),
        _env_file=None,
    )
    settings.ai_provider = configured.ai_provider
    settings.gemini_model = configured.gemini_model
    output = {
        "summary": "Sem anomalias",
        "justification": "Sem ação fundamentada",
        "evidence": [],
        "suggestions": [],
    }
    response = (
        output
        if provider == "structured-http"
        else {
            "candidates": [
                {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(output)}]}}
            ],
        }
    )
    client.app.dependency_overrides[get_ai_adapter] = lambda: AIAdapter(
        configured, httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    )
    created = client.post(
        "/admin/recommendations", headers=headers, json={"kind": "access_anomalies"}
    )
    assert created.status_code == 201
    record = created.json()
    assert record["provider"] == provider
    assert record["model"] == (
        "gemini-3.5-flash-lite" if provider == "gemini" else settings.ai_model
    )
    assert record["simulated"] is False
    path = f"/admin/recommendations/{record['id']}"
    audit = client.get("/admin/audit", headers=headers)
    assert audit.status_code == 200
    before = audit.json()
    assert (
        client.post(path + "/approve", headers=headers, json={"expected_version": 1}).status_code
        == 409
    )
    assert client.get(path, headers=headers).json() == record
    assert client.get("/admin/audit", headers=headers).json() == before
    assert (
        client.post(path + "/reject", headers=headers, json={"expected_version": 1}).json()[
            "status"
        ]
        == "rejected"
    )


@pytest.mark.parametrize("failure", ["quota", "invented_user", "invented_evidence", "bad_uuid"])
def test_gemini_failure_does_not_persist_or_change_accounts(
    client, user, engine, settings, failure
):
    from mod1_auth.ai_adapter import AIAdapter
    from mod1_auth.dependencies import get_ai_adapter

    promote(engine, user)
    headers = bearer(login(client, user).json())
    configured = type(settings)(
        **(
            settings.model_dump()
            | {
                "ai_provider": "gemini",
                "gemini_api_key": "test-only-key",
            }
        ),
        _env_file=None,
    )

    def handler(request):
        if failure == "quota":
            return httpx.Response(429, text="private provider details")
        context = json.loads(json.loads(request.content)["contents"][0]["parts"][0]["text"])[
            "context"
        ]
        event = context["audit_events"][0]["id"]
        output = {
            "summary": "Revisar",
            "justification": "Evento auditado",
            "evidence": [event],
            "suggestions": [
                {
                    "user_id": str(user.id),
                    "action": "review_login",
                    "reason": "Revisão humana",
                    "evidence_ids": [event],
                }
            ],
        }
        if failure == "invented_user":
            output["suggestions"][0]["user_id"] = str(uuid4())
        elif failure == "invented_evidence":
            output["suggestions"][0]["evidence_ids"] = [str(uuid4())]
        else:
            output["suggestions"][0]["user_id"] = "invalid-uuid"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(output)}]}}
                ]
            },
        )

    client.app.dependency_overrides[get_ai_adapter] = lambda: AIAdapter(
        configured, httpx.MockTransport(handler)
    )
    before = client.get("/admin/recommendations", headers=headers).json()
    audit = client.get("/admin/audit", headers=headers).json()
    response = client.post(
        "/admin/recommendations", headers=headers, json={"kind": "access_anomalies"}
    )
    assert response.status_code == 503
    assert "private provider details" not in response.text
    assert client.get("/admin/recommendations", headers=headers).json() == before
    assert client.get("/admin/audit", headers=headers).json() == audit
    assert client.get("/auth/me", headers=headers).json()["is_active"] is True


def test_admin_ai_disabled_and_nonadmin_denied(client, user, engine):
    headers = bearer(login(client, user).json())
    assert (
        client.post(
            "/admin/recommendations", headers=headers, json={"kind": "access_anomalies"}
        ).status_code
        == 403
    )
    promote(engine, user)
    assert (
        client.post(
            "/admin/recommendations", headers=headers, json={"kind": "access_anomalies"}
        ).status_code
        == 503
    )


def test_structured_ai_uses_actual_audit_and_approval_never_changes_access(
    client, user, engine, settings
):
    from mod1_auth.ai_adapter import AIAdapter
    from mod1_auth.dependencies import get_ai_adapter

    promote(engine, user)
    settings.ai_base_url = "http://127.0.0.1:9765"
    settings.ai_simulated = True
    headers = bearer(login(client, user).json())

    def handler(request):
        data = json.loads(request.content)
        event = data["context"]["audit_events"][0]
        assert data["kind"] == "access_anomalies" and data["schema_version"] == 1
        assert all("email" not in person for person in data["context"]["users"])
        return httpx.Response(
            200,
            json={
                "summary": "Review authentication activity",
                "justification": "Audit evidence supplied",
                "evidence": [event["id"]],
                "suggestions": [
                    {
                        "user_id": str(user.id),
                        "action": "review_login",
                        "reason": "Human review requested",
                        "evidence_ids": [event["id"]],
                    }
                ],
            },
        )

    client.app.dependency_overrides[get_ai_adapter] = lambda: AIAdapter(
        settings, httpx.MockTransport(handler)
    )
    response = client.post(
        "/admin/recommendations", headers=headers, json={"kind": "access_anomalies"}
    )
    assert response.status_code == 201
    recommendation = response.json()
    assert recommendation["simulated"] is True
    assert recommendation["status"] == "pending"
    rid = recommendation["id"]
    approved = client.post(
        f"/admin/recommendations/{rid}/approve", headers=headers, json={"expected_version": 1}
    )
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert client.get("/auth/me", headers=headers).json()["is_active"] is True
    assert (
        client.post(
            f"/admin/recommendations/{rid}/approve", headers=headers, json={"expected_version": 1}
        ).status_code
        == 409
    )


def test_ai_rejects_invented_evidence_and_stale_context(client, user, engine, settings):
    from mod1_auth.ai_adapter import AIAdapter
    from mod1_auth.dependencies import get_ai_adapter

    promote(engine, user)
    settings.ai_base_url = "http://127.0.0.1:9765"
    headers = bearer(login(client, user).json())
    invalid = {
        "summary": "Invented",
        "justification": "No real evidence",
        "evidence": [str(uuid4())],
        "suggestions": [],
    }
    client.app.dependency_overrides[get_ai_adapter] = lambda: AIAdapter(
        settings, httpx.MockTransport(lambda request: httpx.Response(200, json=invalid))
    )
    assert (
        client.post(
            "/admin/recommendations", headers=headers, json={"kind": "access_anomalies"}
        ).status_code
        == 503
    )
