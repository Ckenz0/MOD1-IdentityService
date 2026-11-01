from datetime import UTC, datetime
from uuid import uuid4

from test_recovery_mfa import promote
from test_sessions import bearer, login

from mod1_auth.database import create_session_factory
from mod1_auth.repositories import UserRepository
from mod1_auth.services import UserService


def test_logout_is_idempotent(client, user):
    headers = bearer(login(client, user).json())
    assert client.post("/auth/logout", headers=headers, json={}).status_code == 204
    assert client.post("/auth/logout", headers=headers, json={}).status_code == 204


def test_deadlines_are_server_enforced_and_reads_do_not_extend(client, user, engine):
    first = login(client, user).json()
    headers = bearer(first)
    with create_session_factory(engine)() as session:
        store = UserRepository(session).identity
        with store.atomic():
            state = store.get("session:" + first["session_id"])
            state["idle"] = datetime.now(UTC).timestamp() - 1
            store.put("session:" + first["session_id"], "session", str(user.id), state)
    assert client.get("/auth/me", headers=headers).status_code == 401
    assert client.post("/auth/session/activity", headers=headers, json={}).status_code == 401
    assert (
        client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code
        == 401
    )


def test_admin_unlock_jti_and_deactivation(client, user, engine):
    promote(engine, user)
    first = login(client, user).json()
    headers = bearer(first)
    with create_session_factory(engine)() as session:
        colleague = UserService(UserRepository(session)).create_user(
            email="other@example.com", display_name="Other", password="colleague-password"
        )
    for _ in range(5):
        assert (
            client.post(
                "/auth/token", data={"username": colleague.email, "password": "wrong"}
            ).status_code
            == 401
        )
    assert (
        client.post(f"/admin/users/{colleague.id}/unlock", headers=headers, json={}).status_code
        == 204
    )
    logged = client.post(
        "/auth/token", data={"username": colleague.email, "password": "colleague-password"}
    ).json()
    assert "access_token" in logged
    # Claims are decoded through the app's configured verifier, never untrusted.
    jti = client.app.state.tokens.verify(logged["access_token"]).jti
    assert (
        client.post("/admin/tokens/revoke", headers=headers, json={"jti": str(jti)}).status_code
        == 204
    )
    assert client.get("/auth/me", headers=bearer(logged)).status_code == 401
    assert (
        client.patch(
            f"/admin/users/{colleague.id}", headers=headers, json={"is_active": False}
        ).status_code
        == 200
    )
    assert client.get(f"/auth/users/{colleague.id}/status", headers=headers).json() == {
        "id": str(colleague.id),
        "is_active": False,
    }
    assert client.get(f"/auth/users/{uuid4()}/status", headers=headers).status_code == 404


def test_no_transport_is_explicitly_unavailable(client, user):
    found = client.post("/auth/password/reset/request", json={"email": user.email})
    absent = client.post("/auth/password/reset/request", json={"email": "absent@example.com"})
    assert found.status_code == absent.status_code == 503
    assert found.json() == absent.json()


def test_password_reset_between_verification_and_session_creation_rejects_old_password(
    client, user, engine, monkeypatch
):
    import mod1_auth.identity_service as identity_module
    from mod1_auth.security import hash_password

    verify = identity_module.verify_password
    reset_committed = False

    def reset_after_verification(password, encoded):
        nonlocal reset_committed
        valid = verify(password, encoded)
        if valid and not reset_committed:
            # Deterministically interleave a committed reset after the expensive
            # password check but before login obtains its security lock.
            with create_session_factory(engine)() as session:
                store = UserRepository(session).identity
                with store.atomic():
                    store.replace_password(str(user.id), hash_password("replacement-password"))
                    store.revoke_all(user.id)
            reset_committed = True
        return valid

    monkeypatch.setattr(identity_module, "verify_password", reset_after_verification)
    response = login(client, user)
    assert reset_committed
    assert response.status_code == 401
