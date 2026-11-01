"""Official Resend wire contract, controlled transport; no external sends."""

import json
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from mod1_auth.database import create_session_factory
from mod1_auth.mail_adapter import MailAdapter, MailUnavailable
from mod1_auth.repositories import UserRepository
from mod1_auth.resend_adapter import ResendAdapter, ResendUnavailable

KEY = "re_synthetic_test_key_never_a_real_credential"
SENDER = "Módulo 1 <access@example.com>"


@pytest.fixture
def configured(settings):
    settings.mail_provider = "resend"
    settings.resend_api_key = SecretStr(KEY)
    settings.resend_from = SENDER
    return settings


@pytest.fixture
def store(engine):
    with create_session_factory(engine)() as session:
        yield UserRepository(session).identity


def test_resend_posts_transactional_text_to_fixed_https_endpoint(configured, store):
    calls = []

    def send(request):
        calls.append(request)
        return httpx.Response(200, json={"id": str(uuid4())})

    with httpx.Client(transport=httpx.MockTransport(send)) as http:
        mail = MailAdapter(configured, store, http_client=http)
        mail.send(
            "person@example.com",
            "Confirme seu e-mail",
            "http://127.0.0.1:5173/#verify-email=synthetic",
        )
    assert len(calls) == 1
    request = calls[0]
    assert request.method == "POST" and str(request.url) == "https://api.resend.com/emails"
    assert request.headers["Authorization"] == "Bearer " + KEY
    assert request.headers["User-Agent"].startswith("mod1-auth/")
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content) == {
        "from": SENDER,
        "to": ["person@example.com"],
        "subject": "Confirme seu e-mail",
        "text": "http://127.0.0.1:5173/#verify-email=synthetic",
    }
    assert store.items("mail") == []
    assert KEY not in repr(configured)


def test_same_payload_reuses_hashed_idempotency_without_suppressing_other_mail(configured, store):
    keys = []

    def send(request):
        keys.append(request.headers["Idempotency-Key"])
        return httpx.Response(200, json={"id": str(uuid4())})

    with httpx.Client(transport=httpx.MockTransport(send)) as http:
        mail = MailAdapter(configured, store, http_client=http)
        for recipient, body in [
            ("a@example.com", "opaque-token-one"),
            ("a@example.com", "opaque-token-one"),
            ("a@example.com", "opaque-token-two"),
            ("b@example.com", "opaque-token-one"),
        ]:
            mail.send(recipient, "Recuperação", body)
    assert keys[0] == keys[1] and len(set(keys)) == 3
    assert all(len(key) <= 256 and "opaque-token" not in key and "@" not in key for key in keys)


@pytest.mark.parametrize("status", [302, 400, 401, 403, 409, 429, 500, 503])
def test_provider_failures_are_sanitized_without_redirect_or_retry(configured, store, status):
    calls = []

    def send(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://untrusted.example/steal"},
            json={"message": "private-provider-body " + KEY},
        )

    with httpx.Client(transport=httpx.MockTransport(send), follow_redirects=True) as http:
        mail = MailAdapter(configured, store, http_client=http)
        with pytest.raises(MailUnavailable) as error:
            mail.send("person@example.com", "Recuperação", "opaque-link")
    assert len(calls) == 1
    assert KEY not in str(error.value) and "private-provider" not in str(error.value)


@pytest.mark.parametrize("body", [{}, {"id": "invalid"}, [], {"id": None}])
def test_malformed_success_is_not_reported_as_accepted(configured, store, body):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    ) as http:
        with pytest.raises(MailUnavailable):
            MailAdapter(configured, store, http_client=http).send(
                "a@example.com", "subject", "body"
            )


def test_network_timeout_and_oversized_response_fail_closed(configured, store):
    def timeout(request):
        raise httpx.ReadTimeout("private-timeout-detail", request=request)

    for transport in [
        httpx.MockTransport(timeout),
        httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 300000)),
        httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"[" * 7000 + b"0" + b"]" * 7000)
        ),
    ]:
        with httpx.Client(transport=transport) as http:
            with pytest.raises(MailUnavailable) as error:
                MailAdapter(configured, store, http_client=http).send(
                    "a@example.com", "subject", "body"
                )
            assert "private-timeout" not in str(error.value)


def test_explicit_resend_does_not_fall_back_to_enabled_local_mailbox(configured, store):
    configured.local_mailbox_enabled = True
    calls = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: calls.append(request) or httpx.Response(200, json={"id": str(uuid4())})
        )
    ) as http:
        MailAdapter(configured, store, http_client=http).send("a@example.com", "subject", "body")
    assert len(calls) == 1 and store.items("mail") == []


def test_explicit_missing_resend_settings_fail_without_local_fallback(configured, store):
    configured.local_mailbox_enabled = True
    configured.resend_api_key = None
    with pytest.raises(MailUnavailable):
        MailAdapter(configured, store).require_configured()
    assert store.items("mail") == []


def test_auto_selects_resend_when_configured_without_local_override(configured, store):
    configured.mail_provider = "auto"
    configured.local_mailbox_enabled = False
    calls = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: calls.append(request) or httpx.Response(200, json={"id": str(uuid4())})
        )
    ) as http:
        MailAdapter(configured, store, http_client=http).send("a@example.com", "subject", "body")
    assert len(calls) == 1


def test_partial_resend_configuration_cannot_silently_use_smtp(configured, store):
    configured.mail_provider = "auto"
    configured.smtp_host = "smtp.example.com"
    configured.resend_from = None
    with pytest.raises(MailUnavailable):
        MailAdapter(configured, store).require_configured()


def test_explicit_disabled_mode_overrides_local_mailbox(configured, store):
    configured.mail_provider = "disabled"
    configured.local_mailbox_enabled = True
    with pytest.raises(MailUnavailable):
        MailAdapter(configured, store).send("a@example.com", "subject", "body")
    assert store.items("mail") == []


@pytest.mark.parametrize(
    "changes",
    [
        {"resend_from": "not-an-email"},
        {"resend_from": "a@example.com\r\nBcc: b@example.com"},
        {"resend_from": "a@example.com, b@example.com"},
        {"resend_api_key": " "},
        {"resend_timeout_seconds": 0},
        {"resend_timeout_seconds": 31},
        {"mail_provider": "unknown"},
    ],
)
def test_resend_configuration_is_validated_without_echoing_secrets(settings, changes):
    with pytest.raises(ValidationError):
        type(settings)(**(settings.model_dump() | changes), _env_file=None)


def test_configured_resend_outage_does_not_enumerate_reset_accounts(
    configured, client, user, monkeypatch
):
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(True)
        raise ResendUnavailable("private-provider-body " + KEY)

    monkeypatch.setattr(ResendAdapter, "send", unavailable)
    found = client.post("/auth/password/reset/request", json={"email": user.email})
    absent = client.post("/auth/password/reset/request", json={"email": "absent@example.com"})
    assert found.status_code == absent.status_code == 202
    assert found.json() == absent.json()
    assert KEY not in found.text and "private-provider" not in found.text
    assert (
        client.post("/auth/password/reset/request", json={"email": user.email}).status_code == 202
    )
    assert len(calls) == 1  # Failed attempts also observe the cooldown.
    with create_session_factory(client.app.state.engine)() as session:
        repository = UserRepository(session).identity
        assert repository.items("credential") == []
        assert any(
            event["action"] == "password_reset_delivery_failed"
            for event in repository.items("audit")
        )


def test_resend_reset_and_email_confirmation_use_real_credential_rules(
    configured, client, user, monkeypatch
):
    from urllib.parse import parse_qs, urlsplit

    from test_sessions import bearer, login

    messages = []
    original = ResendAdapter.request

    def controlled(adapter, client, payload, headers):
        def accepted(request):
            messages.append(json.loads(request.content))
            return httpx.Response(200, json={"id": str(uuid4())})

        with httpx.Client(transport=httpx.MockTransport(accepted)) as http:
            original(adapter, http, payload, headers)

    monkeypatch.setattr(ResendAdapter, "request", controlled)
    old = bearer(login(client, user).json())
    assert (
        client.post("/auth/password/reset/request", json={"email": user.email}).status_code == 202
    )
    reset = parse_qs(urlsplit(messages[-1]["text"]).fragment)["recovery"][0]
    assert (
        client.post(
            "/auth/password/reset/confirm",
            json={"token": reset, "new_password": "replacement-password-2026"},
        ).status_code
        == 204
    )
    assert client.get("/auth/me", headers=old).status_code == 401
    fresh = client.post(
        "/auth/token", data={"username": user.email, "password": "replacement-password-2026"}
    )
    assert fresh.status_code == 200
    headers = bearer(fresh.json())
    assert client.post("/auth/email/request", json={}, headers=headers).status_code == 202
    verify = parse_qs(urlsplit(messages[-1]["text"]).fragment)["verify-email"][0]
    assert client.post("/auth/email/confirm", json={"token": verify}).status_code == 204
    assert client.get("/auth/me", headers=headers).json()["email_verified"] is True
    assert client.post("/auth/email/confirm", json={"token": verify}).status_code == 400
    assert len(messages) == 2 and all(message["to"] == [user.email] for message in messages)
    assert client.get("/admin/mailbox", headers=headers).status_code == 404
