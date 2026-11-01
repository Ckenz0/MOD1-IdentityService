import json
from uuid import uuid4

import httpx
from test_recovery_mfa import promote
from test_sessions import bearer, login


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
