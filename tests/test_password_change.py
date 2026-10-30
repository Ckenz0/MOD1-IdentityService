from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mod1_auth.config import Settings
from mod1_auth.database import create_session_factory
from mod1_auth.main import create_app
from mod1_auth.repositories import UserRecord, UserRepository
from mod1_auth.security import TokenService, load_key_material, verify_password
from mod1_auth.services import AuthService

CURRENT = "  password12345  "
NEW = "  nova senha literal ç  "


def authorization(client, user):
    token = client.post("/auth/token", data={"username": user.email, "password": CURRENT}).json()[
        "access_token"
    ]
    return {"Authorization": "Bearer " + token}


def test_policy_is_public_configurable_and_not_cached(client, settings):
    response = client.get("/auth/password-policy")
    assert response.status_code == 200
    assert response.json() == {"min_length": 12, "max_length": 128}
    assert response.headers["cache-control"] == "no-store"
    settings.password_min_length = 20
    with TestClient(create_app(settings)) as configured:
        assert configured.get("/auth/password-policy").json() == {
            "min_length": 20,
            "max_length": 128,
        }
        rejected = configured.post(
            "/auth/register",
            json={"email": "new@example.com", "display_name": "New", "password": "x" * 19},
        )
        assert rejected.status_code == 422
        assert "x" * 19 not in rejected.text
        assert (
            configured.post(
                "/auth/register",
                json={"email": "new@example.com", "display_name": "New", "password": "x" * 20},
            ).status_code
            == 202
        )


@pytest.mark.parametrize("minimum", [11, 129])
def test_configuration_rejects_unsafe_password_policy(settings, minimum):
    with pytest.raises(ValidationError):
        Settings(**(settings.model_dump() | {"password_min_length": minimum}), _env_file=None)


def test_change_persists_literal_password_and_preserves_identity(client, user, engine):
    headers = authorization(client, user)
    response = client.post(
        "/auth/password", headers=headers, json={"current_password": CURRENT, "new_password": NEW}
    )
    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    for password, expected in [(CURRENT, 401), (NEW.strip(), 401), (NEW, 200)]:
        assert (
            client.post(
                "/auth/token", data={"username": user.email, "password": password}
            ).status_code
            == expected
        )
    with create_session_factory(engine)() as session:
        changed = UserRepository(session).get_by_id(user.id)
        assert changed.email == user.email
        assert changed.created_at == user.created_at
        assert changed.is_active is True
        assert changed.password_hash != user.password_hash
        assert verify_password(NEW, changed.password_hash)
    # This feature deliberately retains existing JWT TTL; no revocation claim.
    assert client.get("/auth/me", headers=headers).status_code == 200


@pytest.mark.parametrize(
    "current,new", [("wrong", NEW), (CURRENT.strip(), NEW), (CURRENT, CURRENT)]
)
def test_rejection_is_uniform_and_preserves_password(client, user, current, new):
    response = client.post(
        "/auth/password",
        headers=authorization(client, user),
        json={"current_password": current, "new_password": new},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Password change rejected"}
    assert response.headers["cache-control"] == "no-store"
    assert (
        client.post("/auth/token", data={"username": user.email, "password": CURRENT}).status_code
        == 200
    )


@pytest.mark.parametrize("kind", ["missing", "malformed", "invalid", "unknown", "inactive"])
def test_change_requires_same_authentication_as_me(client, user, settings, engine, kind):
    headers = {}
    if kind == "malformed":
        headers = {"Authorization": "Basic invalid"}
    elif kind == "invalid":
        headers = {"Authorization": "Bearer invalid"}
    elif kind in ("unknown", "inactive"):
        tokens = TokenService(load_key_material(settings.jwt_private_key_path), settings)
        token = tokens.issue(uuid4() if kind == "unknown" else user.id).access_token
        headers = {"Authorization": f"Bearer {token}"}
        if kind == "inactive":
            with create_session_factory(engine)() as session:
                UserRepository(session).set_active(user.id, False)
    response = client.post(
        "/auth/password", headers=headers, json={"current_password": CURRENT, "new_password": NEW}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid authentication credentials"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "changes",
    [
        {"new_password": "short-secret"[:11]},
        {"new_password": "x" * 129},
        {"current_password": "x" * 129},
        {"current_password": None},
        {"new_password": 123456789012},
        {"extra": "secret-extra"},
    ],
)
def test_invalid_change_does_not_echo_secrets(client, user, changes):
    response = client.post(
        "/auth/password",
        headers=authorization(client, user),
        json={"current_password": CURRENT, "new_password": NEW} | changes,
    )
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    for secret in [CURRENT, NEW, "secret-extra", "x" * 129, "short-secre"]:
        assert secret not in response.text
    assert all("input" not in error for error in response.json()["detail"])


def test_change_database_failure_is_safe_and_not_cached(client, user, engine):
    headers = authorization(client, user)
    UserRecord.__table__.drop(engine)
    response = client.post(
        "/auth/password", headers=headers, json={"current_password": CURRENT, "new_password": NEW}
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Service unavailable"}
    assert response.headers["cache-control"] == "no-store"


def test_compare_and_swap_prevents_stale_hash_or_inactive_update(engine, user):
    with create_session_factory(engine)() as session:
        repository = UserRepository(session)
        assert repository.change_password(user.id, user.password_hash, "replacement-hash") is True
        assert repository.change_password(user.id, user.password_hash, "stale-hash") is False
        repository.set_active(user.id, False)
        assert repository.change_password(user.id, "replacement-hash", "inactive-hash") is False
        assert repository.get_by_id(user.id).password_hash == "replacement-hash"


def test_two_simultaneous_changes_accept_only_one(engine, user, settings, monkeypatch):
    from mod1_auth.domain import PasswordChangeRejectedError

    barrier = Barrier(2)
    original = UserRepository.change_password

    def synchronized_update(self, *args):
        barrier.wait(timeout=10)
        return original(self, *args)

    monkeypatch.setattr(UserRepository, "change_password", synchronized_update)
    tokens = TokenService(load_key_material(settings.jwt_private_key_path), settings)
    token = tokens.issue(user.id).access_token

    def change(password):
        with create_session_factory(engine)() as session:
            service = AuthService(UserRepository(session), tokens)
            try:
                service.change_password(token, CURRENT, password)
                return password
            except PasswordChangeRejectedError:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, [NEW, "second-new-password"]))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    with create_session_factory(engine)() as session:
        stored = UserRepository(session).get_by_id(user.id)
        assert verify_password(winners[0], stored.password_hash)


def test_configured_minimum_applies_to_change(client, user, settings):
    headers = authorization(client, user)
    settings.password_min_length = 24
    with TestClient(create_app(settings)) as configured:
        for password, expected in [("x" * 23, 422), ("x" * 24, 204)]:
            response = configured.post(
                "/auth/password",
                headers=headers,
                json={"current_password": CURRENT, "new_password": password},
            )
            assert response.status_code == expected


def test_maximum_length_password_can_be_used_for_next_change(client, user):
    headers = authorization(client, user)
    for current, new in [(CURRENT, "ç" * 128), ("ç" * 128, NEW)]:
        response = client.post(
            "/auth/password",
            headers=headers,
            json={"current_password": current, "new_password": new},
        )
        assert response.status_code == 204


def test_openapi_describes_password_authentication_and_empty_success(client):
    schema = client.get("/openapi.json").json()
    assert schema["info"]["version"] == "0.3.0"
    assert not schema["paths"]["/auth/password-policy"]["get"].get("security")
    change = schema["paths"]["/auth/password"]["post"]
    assert change["security"] == [{"OAuth2PasswordBearer": []}]
    assert "content" not in change["responses"]["204"]
