import base64
import hashlib
import hmac
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from test_sessions import bearer, login

from mod1_auth.database import create_session_factory
from mod1_auth.main import create_app
from mod1_auth.repositories import UserRepository


def promote(engine, user):
    with create_session_factory(engine)() as session:
        store = UserRepository(session).identity
        with store.atomic():
            account = store.account(user.id)
            account["is_admin"] = True
            store.save_account(user.id, account)


def code_for(secret, step=None):
    step = int(time.time() // 30) if step is None else step
    data = hmac.new(base64.b32decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = data[-1] & 15
    return str((struct.unpack(">I", data[offset : offset + 4])[0] & 0x7FFFFFFF) % 1000000).zfill(6)


def mailbox_token(client, headers, fragment):
    messages = client.get("/admin/mailbox", headers=headers)
    assert messages.status_code == 200
    body = messages.json()["items"][0]["body"]
    assert body.startswith("http://127.0.0.1:5173/#" + fragment + "=")
    return urlsplit(body).fragment.split("=", 1)[1]


def test_reset_is_uniform_single_use_and_revokes_sessions(settings, engine, user):
    settings.local_mailbox_enabled = True
    promote(engine, user)
    with TestClient(create_app(settings)) as client:
        headers = bearer(login(client, user).json())
        found = client.post("/auth/password/reset/request", json={"email": user.email})
        absent = client.post("/auth/password/reset/request", json={"email": "absent@example.com"})
        assert found.status_code == absent.status_code == 202
        assert found.json() == absent.json()
        token = mailbox_token(client, headers, "recovery")
        response = client.post(
            "/auth/password/reset/confirm",
            json={"token": token, "new_password": "new-password-for-reset"},
        )
        assert response.status_code == 204
        assert client.get("/auth/me", headers=headers).status_code == 401
        assert (
            client.post(
                "/auth/password/reset/confirm",
                json={"token": token, "new_password": "another-password"},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/auth/token", data={"username": user.email, "password": "new-password-for-reset"}
            ).status_code
            == 200
        )


def test_verify_email_and_disabled_mailbox(settings, engine, user, client):
    promote(engine, user)
    headers = bearer(login(client, user).json())
    assert client.get("/admin/mailbox", headers=headers).status_code == 404
    settings.local_mailbox_enabled = True
    with TestClient(create_app(settings)) as configured:
        assert configured.post("/auth/email/request", headers=headers, json={}).status_code == 202
        token = mailbox_token(configured, headers, "verify-email")
        assert configured.post("/auth/email/confirm", json={"token": token}).status_code == 204
        assert configured.get("/auth/me", headers=headers).json()["email_verified"] is True
        assert configured.post("/auth/email/confirm", json={"token": token}).status_code == 400


def test_mfa_challenge_recovery_replay_and_reset_no_bypass(settings, engine, user):
    settings.local_mailbox_enabled = True
    settings.mfa_encryption_key = type(settings.database_url)(Fernet.generate_key().decode())
    promote(engine, user)
    with TestClient(create_app(settings)) as client:
        headers = bearer(login(client, user).json())
        setup = client.post(
            "/auth/mfa/setup", headers=headers, json={"password": "  password12345  "}
        )
        assert setup.status_code == 200
        secret = setup.json()["secret"]
        enabled = client.post("/auth/mfa/enable", headers=headers, json={"code": code_for(secret)})
        assert enabled.status_code == 200
        recovery = enabled.json()["recovery_codes"]
        challenge = login(client, user).json()
        assert challenge["mfa_required"] is True and "access_token" not in challenge
        assert (
            client.post(
                "/auth/mfa/verify",
                json={"challenge_token": challenge["challenge_token"], "code": code_for(secret)},
            ).status_code
            == 401
        )
        completed = client.post(
            "/auth/mfa/verify",
            json={"challenge_token": challenge["challenge_token"], "recovery_code": recovery[0]},
        )
        assert completed.status_code == 200
        assert (
            client.post(
                "/auth/mfa/verify",
                json={
                    "challenge_token": challenge["challenge_token"],
                    "recovery_code": recovery[1],
                },
            ).status_code
            == 401
        )
        second = login(client, user).json()
        assert (
            client.post(
                "/auth/mfa/verify",
                json={"challenge_token": second["challenge_token"], "recovery_code": recovery[0]},
            ).status_code
            == 401
        )
        current = bearer(completed.json())
        assert (
            client.post("/auth/password/reset/request", json={"email": user.email}).status_code
            == 202
        )
        token = mailbox_token(client, current, "recovery")
        assert (
            client.post(
                "/auth/password/reset/confirm",
                json={"token": token, "new_password": "another-new-password"},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/auth/password/reset/confirm",
                json={
                    "token": token,
                    "new_password": "another-new-password",
                    "recovery_code": recovery[1],
                },
            ).status_code
            == 204
        )
        with create_session_factory(engine)() as session:
            state = UserRepository(session).identity.account(user.id)
            assert state["mfa_enabled"] is True
            assert secret not in str(state)
            assert not any(c in str(state) for c in recovery)


def test_concurrent_reset_has_one_winner(settings, engine, user):
    settings.local_mailbox_enabled = True
    promote(engine, user)
    with TestClient(create_app(settings)) as client:
        headers = bearer(login(client, user).json())
        assert (
            client.post("/auth/password/reset/request", json={"email": user.email}).status_code
            == 202
        )
        token = mailbox_token(client, headers, "recovery")

        def consume(_):
            return client.post(
                "/auth/password/reset/confirm",
                json={"token": token, "new_password": "new-password-concurrent"},
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(consume, range(2))) == [204, 400]


def test_admin_provisions_by_setup_link_without_assigning_admin(settings, engine, user):
    settings.local_mailbox_enabled = True
    promote(engine, user)
    with TestClient(create_app(settings)) as client:
        headers = bearer(login(client, user).json())
        body = {"display_name": "New colleague", "email": "colleague@example.com"}
        assert client.post("/admin/users", headers=headers, json=body).status_code == 202
        token = mailbox_token(client, headers, "recovery")
        assert (
            client.post(
                "/auth/password/reset/confirm",
                json={"token": token, "new_password": "colleague-password"},
            ).status_code
            == 204
        )
        new_token = client.post(
            "/auth/token", data={"username": body["email"], "password": "colleague-password"}
        ).json()
        assert client.get("/auth/me", headers=bearer(new_token)).json()["is_admin"] is False


def test_mfa_failure_limit_cannot_be_reset_by_repeating_password(settings, engine, user):
    settings.mfa_encryption_key = type(settings.database_url)(Fernet.generate_key().decode())
    with TestClient(create_app(settings)) as client:
        headers = bearer(login(client, user).json())
        setup = client.post(
            "/auth/mfa/setup", headers=headers, json={"password": "  password12345  "}
        ).json()
        enabled = client.post(
            "/auth/mfa/enable", headers=headers, json={"code": code_for(setup["secret"])}
        ).json()
        used = code_for(setup["secret"])  # Already consumed by enable; always rejected.
        for _ in range(5):
            challenge = login(client, user).json()
            assert (
                client.post(
                    "/auth/mfa/verify",
                    json={
                        "challenge_token": challenge["challenge_token"],
                        "code": used,
                    },
                ).status_code
                == 401
            )
        assert login(client, user).status_code == 401
        assert enabled["recovery_codes"]


def test_password_change_invalidates_outstanding_mfa_challenge(settings, engine, user):
    settings.mfa_encryption_key = type(settings.database_url)(Fernet.generate_key().decode())
    with TestClient(create_app(settings)) as client:
        headers = bearer(login(client, user).json())
        setup = client.post(
            "/auth/mfa/setup", headers=headers, json={"password": "  password12345  "}
        ).json()
        recovery = client.post(
            "/auth/mfa/enable", headers=headers, json={"code": code_for(setup["secret"])}
        ).json()["recovery_codes"]
        challenge = login(client, user).json()["challenge_token"]
        assert (
            client.post(
                "/auth/password",
                headers=headers,
                json={
                    "current_password": "  password12345  ",
                    "new_password": "new-password-today",
                },
            ).status_code
            == 204
        )
        assert (
            client.post(
                "/auth/mfa/verify",
                json={
                    "challenge_token": challenge,
                    "recovery_code": recovery[0],
                },
            ).status_code
            == 401
        )
